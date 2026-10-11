#!/usr/bin/env python3
"""m9_rins_cp — RINS m9 (voisinage par accord LP / best/) résolu par CP-SAT dans un sous-processus.

Ce processus : construction du modèle m9 + LP racine (cache npz, highspy chargé seulement si la LP n'est pas en cache),
fixation RINS (fonctions de m9_rins.py), export du MIP réduit (colonnes libres) en npz, appel de
src/m9_rins_cp_solve.py (ortools), reconstruction de la solution complète, décodage, save_if_better.
Usage : python src/m9_rins_cp.py 6 [params m9] --thresholds 0.8,0.7,0.9 --frac 1.0 --eps0 1e-6 --fix-roles 1 --cutoff 1 \
        --slice 900 --cp-workers 8 --until "2026-10-11 15:30:00 UTC" --seed w --tag x --save
"""
import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402
import m9_rins as R  # noqa: E402
from m9_rins import log  # noqa: E402


def parse_until(s):
    import calendar
    if not s:
        return None
    out = subprocess.run(["date", "-u", "-d", s, "+%s"], capture_output=True, text=True)
    return float(out.stdout.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("--start", default=None)
    ap.add_argument("--extra", nargs="*", default=[])
    ap.add_argument("--theta", type=float, default=5.0)
    ap.add_argument("--theta-gen", type=float, default=None)
    ap.add_argument("--k1", type=int, default=10); ap.add_argument("--k2", type=int, default=10); ap.add_argument("--k3", type=int, default=10)
    ap.add_argument("--eps1", type=int, default=300); ap.add_argument("--eps2", type=int, default=5); ap.add_argument("--eps3", type=int, default=0)
    ap.add_argument("--hcols", type=float, default=0.25)
    ap.add_argument("--kcur", type=int, default=10)
    ap.add_argument("--cross", type=int, default=0)
    ap.add_argument("--fix-gen", action="store_true")
    ap.add_argument("--max-cols", type=int, default=250000)
    ap.add_argument("--lp-solver", default="ipm")
    ap.add_argument("--lp-threads", type=int, default=1)
    ap.add_argument("--lp-time", type=float, default=900)
    ap.add_argument("--crossover", type=int, default=0)
    ap.add_argument("--lp-recompute", action="store_true")
    ap.add_argument("--thresholds", default="0.8,0.7,0.9")
    ap.add_argument("--frac", default="1.0")
    ap.add_argument("--support-eps", type=float, default=1e-6)
    ap.add_argument("--eps0", default="1e-6")
    ap.add_argument("--fix-roles", type=int, default=1)
    ap.add_argument("--frac-roles", type=float, default=1.0)
    ap.add_argument("--roles-lp", type=int, default=0)
    ap.add_argument("--lp-one", type=float, default=1.0)
    ap.add_argument("--cutoff", type=int, default=1)
    ap.add_argument("--slice", type=float, default=900)
    ap.add_argument("--cp-workers", type=int, default=8)
    ap.add_argument("--until", default=None, help="fin UTC (date -d), ex. '2026-10-11 15:30:00 UTC'")
    ap.add_argument("--total", type=float, default=1e9)
    ap.add_argument("--max-rounds", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rins-seed", type=int, default=-1)
    ap.add_argument("--tag", default="x")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--cp-log", type=int, default=0)
    a = ap.parse_args()
    t0 = time.time()
    end = parse_until(a.until)
    if end is not None:
        a.total = min(a.total, end - t0 - 30)
    k = a.instance
    inst = Instance(k)
    rng = np.random.RandomState(a.seed)
    start = a.start or os.path.join(ROOT, "best", f"instance_{k}.json")
    sol = json.load(open(start))
    start_mtime = os.path.getmtime(start)
    from save_if_better import evaluate, save_if_better
    cur_score, ok, msg = evaluate(k, json.dumps(sol), inst.txt)
    log(f"départ {start} : score {cur_score} valide={ok} ; graine {a.seed} tag {a.tag} ; CP-SAT {a.cp_workers} workers, "
        f"tranche {a.slice}s, total {a.total:.0f}s")
    mdl = R.build_model(a, inst, sol, rng)
    x0, nh, nmiss = R.hint_vector(mdl, inst, sol)
    log(f"  hint : {nh} colonnes, {nmiss} manquantes, valeur {-float(np.dot(mdl['obj'], x0)):.0f}")
    if a.fix_gen:
        for g in mdl["G"]:
            j = mdl["yi"][g]; mdl["lo"][j] = mdl["hi"][j] = x0[j]
        for c, pid, kind, tgt in mdl["acol"]:
            if kind == 1:
                mdl["lo"][c] = mdl["hi"][c] = x0[c]
    x_lp, rc_lp, lp_bound = R.solve_lp(a, mdl, x0)
    rseed = (a.seed * 7919 + int(time.time())) % (2 ** 31) if a.rins_seed < 0 else a.rins_seed
    rng = np.random.RandomState(rseed)
    log(f"  graine RINS {rseed}")
    thrs = [float(s) for s in a.thresholds.split(",")]
    fracs = [float(s) for s in a.frac.split(",")]
    eps0s = [float(s) for s in a.eps0.split(",")]
    nrole = mdl["nrole"]; A = mdl["A"]
    scratch = os.path.join(ROOT, "runs", "m9_rins_cp"); os.makedirs(scratch, exist_ok=True)
    rnd = 0
    while rnd < a.max_rounds and time.time() - t0 + 60 < a.total:
        thr = thrs[rnd % len(thrs)]; frac = fracs[(rnd // len(thrs)) % len(fracs)]
        eps0 = eps0s[(rnd // (len(thrs) * len(fracs))) % len(eps0s)]
        rnd += 1
        try:
            if os.path.getmtime(start) != start_mtime:
                so2 = json.load(open(start))
                sc2, ok2, _ = evaluate(k, json.dumps(so2), inst.txt)
                if ok2 and sc2 > cur_score:
                    log(f"  best/ a changé ({sc2} > {cur_score}) : fin du processus pour repartir du nouveau best/")
                    break
                start_mtime = os.path.getmtime(start)
        except Exception as e:
            log(f"  lecture de {start} : {e!r}")
        lo = mdl["lo"].copy(); hi = mdl["hi"].copy(); rhi = mdl["rhi"].copy(); rlo = mdl["rlo"].copy()
        one, zero, roles, extra1, rval = R.choose_rins(a, mdl, inst, x_lp, x0, thr, frac, eps0, rng)
        if a.roles_lp:
            keep = np.array([rval[mdl["zi"][tgt]] > 0.5 if kind == 0 else rval[mdl["yi"][tgt]] > 0.5
                             for (c, pid, kind, tgt) in (mdl["acol"][j] for j in one)], bool) if len(one) else np.zeros(0, bool)
            one = one[keep]
        lo[nrole + one] = 1.0; hi[nrole + one] = 1.0
        hi[nrole + zero] = 0.0
        lo[roles] = rval[roles]; hi[roles] = rval[roles]
        lo[nrole + extra1] = 1.0; hi[nrole + extra1] = 1.0
        if a.cutoff:
            rhi[mdl["RC"]] = -(cur_score + 1) + 1e-6
        free = np.nonzero(hi > lo + 1e-9)[0]
        fixed = np.nonzero(hi <= lo + 1e-9)[0]
        xf = np.zeros(mdl["ncol"]); xf[fixed] = lo[fixed]
        bfix = A @ xf
        rlo2 = rlo - bfix; rhi2 = rhi - bfix
        AF = A[:, free].tocsc()
        # lignes sans colonne libre : faisabilité
        cnt = np.diff(AF.tocsr().indptr)
        bad = np.nonzero((cnt == 0) & ((rlo2 > 1e-6) | (rhi2 < -1e-6)))[0]
        desc = f"un {len(one)} (+{len(extra1)} LP), zéro {len(zero)}, rôles {len(roles)}, libres {len(free)}"
        if len(bad):
            log(f"TOUR {rnd} seuil={thr} frac={frac} eps0={eps0} : {desc} ; fixation incohérente ({len(bad)} lignes) : tour sauté")
            continue
        slice_t = min(a.slice, a.total - (time.time() - t0) - 40)
        if slice_t < 60:
            break
        fin = os.path.join(scratch, f"{a.tag}_r{rnd}_in.npz"); fout = os.path.join(scratch, f"{a.tag}_r{rnd}_out.npz")
        np.savez(fin, indptr=AF.indptr, indices=AF.indices, data=AF.data, rlo=rlo2, rhi=rhi2,
                 obj=mdl["obj"][free], hint=x0[free])
        cmd = [sys.executable, os.path.join(ROOT, "src", "m9_rins_cp_solve.py"), fin, fout, "--workers", str(a.cp_workers),
               "--time", str(slice_t), "--seed", str((rseed + rnd) % 2147483647), "--log", str(a.cp_log)]
        t1 = time.time()
        try:
            pr = subprocess.run(cmd, capture_output=True, text=True, timeout=slice_t + 300)
            for line in pr.stdout.splitlines():
                if line.startswith("[cp]") or "rror" in line:
                    log("  " + line)
            if pr.returncode != 0:
                log(f"  sous-processus CP-SAT code {pr.returncode} : {pr.stderr[-500:]}")
        except subprocess.TimeoutExpired:
            log("  sous-processus CP-SAT : délai dépassé (tué)")
        dt = time.time() - t1
        st = "?"; val = None; bound = None; sc = None; okv = False
        if os.path.exists(fout):
            z = np.load(fout)
            st = str(z["status"]); bound = float(z["bound"]); cst = -float(np.dot(mdl["obj"], xf))
            bound = cst - bound if np.isfinite(bound) else None
            if bool(z["ok"]):
                x = xf.copy(); x[free] = np.round(z["x"])
                val = -float(np.dot(mdl["obj"], x))
                out = decode = R.decode(mdl, inst, x)
                txt = json.dumps(out, separators=(",", ":"))
                sc, okv, msg = evaluate(k, txt, inst.txt)
                if okv and sc > cur_score:
                    outf = os.path.join(ROOT, "runs", f"m9_rins_cp_{a.tag}_r{rnd}.json")
                    with open(outf, "w") as f:
                        f.write(txt)
                    log(f"  *** AMÉLIORATION {cur_score} -> {sc} (écrit {outf})")
                    if a.save:
                        rc_, sc_ = save_if_better(k, txt, method=f"m9 rins cp-sat seuil={thr} frac={frac} cutoff={a.cutoff} "
                                                  f"theta={a.theta} k={a.k1} fixgen={int(a.fix_gen)} seed={a.seed} tag={a.tag}",
                                                  dataset_txt=inst.txt)
                        log(f"  save_if_better -> code {rc_} (score {sc_})")
                        try:
                            start_mtime = os.path.getmtime(start)
                        except Exception:
                            pass
                    cur_score = sc; sol = out
                    x0, nh, nmiss = R.hint_vector(mdl, inst, sol)
            os.remove(fout)
        if os.path.exists(fin):
            os.remove(fin)
        log(f"TOUR {rnd} seuil={thr} frac={frac} eps0={eps0} : {desc} ; MIP réduit {AF.shape[1]} col. × {int(np.sum(cnt > 0))} lignes ; "
            f"CP-SAT {st} en {dt:.0f}s ; valeur {val} (score {sc} valide={okv}) borne {bound} ; courant {cur_score} ; LP {lp_bound:.1f}")
    log(f"fin : {rnd} tours, score courant {cur_score}, total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
