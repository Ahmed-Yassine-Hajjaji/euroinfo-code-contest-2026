#!/usr/bin/env python3
"""Relaxation LP (partie C de notes/ANALYSE.md) : borne supérieure + prix duaux + valeurs primales par modèle.

Variables par modèle : f (plein tarif), h (demi-tarif), y (générateur, mono-modèles réalisables),
z[m,t] ∈ [0, h_m] (besoin t de m couvert par un générateur ; = h_m si le besoin est impossible).
Contraintes : énergie ; par type, données libres (plein tarif) et données totales ; nb de générateurs par type ;
f + h + y ≤ 1. On compte lb (borne basse) comme consommation : borne valide.
Sortie : runs/lp_<k>.json = {"bound", "dual_energy", "dual_free", "dual_total", "dual_gen", "f", "h", "y"}.
"""
import json
import os
import sys
import time

import numpy as np
from scipy.optimize import linprog, milp, LinearConstraint, Bounds
from scipy.sparse import coo_matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402


def solve_lp(inst, mip_time=0.0, fix_eps=None, shrink=(0.0, 0.0)):
    """shrink = (wf, wt) : offre effective = données libres x (1 - wf), données totales x (1 - wt) (gaspillage attendu)."""
    nm = len(inst.value)
    F = [0] * 4
    T = [0] * 4
    for t, s, c in inst.ds:
        T[t] += s
        if not c:
            F[t] += s
    col = 0
    fi, hi, yi = {}, {}, {}
    zi = {}
    obj, ub = [], []
    for m in range(nm):
        feas = all(lb <= u for _, lb, u in inst.reqs[m])
        fi[m] = col; obj.append(-inst.value[m]); ub.append(1.0 if feas else 0.0); col += 1
        hi[m] = col; obj.append(-(inst.value[m] // 2)); ub.append(1.0); col += 1
        if inst.gen_ok[m]:
            yi[m] = col; obj.append(0.0); ub.append(1.0); col += 1
        for t, lb, u in inst.reqs[m]:
            zi[(m, t)] = col; obj.append(0.0); ub.append(1.0); col += 1
    rows, cols, vals, rhs = [], [], [], []
    r = 0
    # énergie
    R_E = r
    for m in range(nm):
        e = inst.energy[m] / inst.cap
        for c in (fi[m], hi[m]) + ((yi[m],) if m in yi else ()):
            rows.append(r); cols.append(c); vals.append(e)
    rhs.append(1.0); r += 1
    # données libres et totales par type (normalisées par l'offre totale du type)
    R_F = list(range(r, r + 4)); r += 4
    R_T = list(range(r, r + 4)); r += 4
    R_G = list(range(r, r + 4)); r += 4
    rhs += [(1 - shrink[0]) * F[t] / max(T[t], 1) for t in range(4)] + [1.0 - shrink[1]] * 4 + [0.0] * 4
    for m in range(nm):
        for t, lb, u in inst.reqs[m]:
            a = lb / max(T[t], 1)
            rows += [R_F[t], R_T[t], R_T[t], R_T[t]]
            cols += [fi[m], fi[m], hi[m], zi[(m, t)]]
            vals += [a, a, a, -a]
            # z_{m,t} ≤ nb de générateurs de type t
            rows.append(R_G[t]); cols.append(zi[(m, t)]); vals.append(1.0)
        if m in yi:
            t, lb, _ = inst.reqs[m][0]
            rows += [R_T[t], R_G[t]]; cols += [yi[m], yi[m]]; vals += [lb / max(T[t], 1), -1.0]
    # f + h + y ≤ 1 ; z ≤ h ; z = h si besoin impossible (z ≥ h)
    for m in range(nm):
        rows += [r, r]; cols += [fi[m], hi[m]]; vals += [1.0, 1.0]
        if m in yi:
            rows.append(r); cols.append(yi[m]); vals.append(1.0)
        rhs.append(1.0); r += 1
        for t, lb, u in inst.reqs[m]:
            rows += [r, r]; cols += [zi[(m, t)], hi[m]]; vals += [1.0, -1.0]; rhs.append(0.0); r += 1
            if lb > u:
                rows += [r, r]; cols += [hi[m], zi[(m, t)]]; vals += [1.0, -1.0]; rhs.append(0.0); r += 1
    A = coo_matrix((vals, (rows, cols)), shape=(r, col)).tocsr()
    if mip_time > 0:
        lo = np.zeros(col)
        hi_b = np.array(ub, dtype=float)
        nfix = None
        if fix_eps is not None:
            # MIP réduit : LP d'abord, puis on fixe les rôles nets (valeur LP <= eps -> 0, >= 1-eps -> 1)
            rl = linprog(np.array(obj), A_ub=A, b_ub=np.array(rhs), bounds=list(zip([0.0] * col, ub)),
                         method="highs")
            xl = rl.x
            nfix = 0
            for m in range(nm):
                for c_ in (fi[m], hi[m]) + ((yi[m],) if m in yi else ()):
                    if xl[c_] <= fix_eps:
                        hi_b[c_] = 0.0; nfix += 1
                    elif xl[c_] >= 1 - fix_eps:
                        lo[c_] = 1.0; nfix += 1
        integ = np.zeros(col)
        for m in range(nm):
            integ[fi[m]] = integ[hi[m]] = 1
            if m in yi:
                integ[yi[m]] = 1
        for c_ in zi.values():
            integ[c_] = 1
        res = milp(np.array(obj), constraints=LinearConstraint(A, -np.inf, np.array(rhs)),
                   bounds=Bounds(lo, hi_b), integrality=integ,
                   options={"time_limit": mip_time, "disp": False, "mip_rel_gap": 0})
        if res.x is None:
            raise RuntimeError(res.message)
        x = np.round(res.x)
        return {
            "bound": float(-res.mip_dual_bound) if getattr(res, "mip_dual_bound", None) is not None else None,
            "value": float(-np.dot(obj, x)), "message": res.message, "fixed": nfix,
            "n_role_vars": sum(3 if m in yi else 2 for m in range(nm)),
            "f": [float(x[fi[m]]) for m in range(nm)],
            "h": [float(x[hi[m]]) for m in range(nm)],
            "y": [float(x[yi[m]]) if m in yi else 0.0 for m in range(nm)],
            "z": [[t for t, _, _ in inst.reqs[m] if x[zi[(m, t)]] > 0.5] for m in range(nm)],
        }
    res = linprog(np.array(obj), A_ub=A, b_ub=np.array(rhs), bounds=list(zip([0.0] * col, ub)), method="highs")
    if res.status != 0:
        raise RuntimeError(res.message)
    x = res.x
    du = -res.ineqlin.marginals  # prix >= 0 des contraintes <=
    return {
        "bound": -res.fun,
        "dual_energy": du[R_E],
        "dual_free": [du[R_F[t]] / max(T[t], 1) for t in range(4)],    # prix par unité de donnée libre
        "dual_total": [du[R_T[t]] / max(T[t], 1) for t in range(4)],   # prix par unité de donnée (tout type)
        "dual_gen": [du[R_G[t]] for t in range(4)],
        "f": [float(x[fi[m]]) for m in range(nm)],
        "h": [float(x[hi[m]]) for m in range(nm)],
        "y": [float(x[yi[m]]) if m in yi else 0.0 for m in range(nm)],
        "z": [[t for t, _, _ in inst.reqs[m] if x[zi[(m, t)]] > 0.5] for m in range(nm)],
    }


def main():
    shrink = (0.0, 0.0)
    if sys.argv[1] == "--shrink":  # python src/lp_bound.py --shrink wf wt [--mip T] k   -> runs/mip_k_sWF_WT.json
        shrink = (float(sys.argv[2]), float(sys.argv[3])); sys.argv = sys.argv[:1] + sys.argv[4:]
    if sys.argv[1] in ("--mip", "--mip-reduced"):
        # python src/lp_bound.py --mip <secondes> k...            -> runs/mip_k.json
        # python src/lp_bound.py --mip-reduced <secondes> k...    -> runs/mipr_k.json (rôles LP nets fixés, eps=1e-6)
        red = sys.argv[1] == "--mip-reduced"
        T = float(sys.argv[2])
        for k in map(int, sys.argv[3:]):
            t0 = time.time()
            out = solve_lp(Instance(k), mip_time=T, fix_eps=1e-6 if red else None, shrink=shrink)
            if red:
                print(f"inst {k}: variables de rôle fixées {out['fixed']} / {out['n_role_vars']}", flush=True)
            suf = f"_s{shrink[0]}_{shrink[1]}" if any(shrink) else ""
            with open(os.path.join(ROOT, "runs", f"{'mipr' if red else 'mip'}_{k}{suf}.json"), "w") as f:
                json.dump(out, f)
            print(f"inst {k}: MIP valeur {out['value']:.0f} borne {out['bound']} ({time.time()-t0:.0f}s) {out['message']}",
                  flush=True)
        return
    for k in map(int, sys.argv[1:]):
        t0 = time.time()
        inst = Instance(k)
        out = solve_lp(inst)
        with open(os.path.join(ROOT, "runs", f"lp_{k}.json"), "w") as f:
            json.dump(out, f)
        print(f"inst {k}: borne LP = {out['bound']:.0f}  ({time.time()-t0:.1f}s)  "
              f"prix énergie={out['dual_energy']:.1f} données libres={['%.2e' % v for v in out['dual_free']]} "
              f"totales={['%.2e' % v for v in out['dual_total']]} gen={['%.1f' % v for v in out['dual_gen']]}",
              flush=True)


if __name__ == "__main__":
    main()
