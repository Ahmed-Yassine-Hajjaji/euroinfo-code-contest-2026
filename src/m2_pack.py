#!/usr/bin/env python3
"""Méthode 2 : ré-empaquetage à RÔLES FIXÉS, par type, en set-partitioning exact (HiGHS ou CP-SAT).

Colonnes = (créneau, sous-ensemble de 1 à 3 datasets) dont la somme tombe dans [lb, lb + δ] (δ adaptatif, les K
colonnes les plus serrées par créneau), + le paquet actuel de chaque créneau et ses variantes à un dataset retiré /
remplacé (créneaux à 4+ datasets). Chaque créneau reçoit exactement une colonne, chaque dataset au plus une ;
objectif : min Σ consommation (= min gaspillage = max de datasets ENTIERS libérés). Rôles, générateurs,
modelMappings et score inchangés ; seules les dataMappings changent.

Mode par blocs (défaut, --block B > 0) : on résout en boucle des sous-problèmes de B créneaux du même type avec leurs
datasets + les datasets libres du type (LP instantanée, amélioration monotone), jusqu'à --time secondes par type.
Mode global (--block 0) : un seul MIP par type sur toutes les colonnes (LP lente au-delà de ~30 k colonnes).

Usage : python src/m2_pack.py <k> --start sol.json --out out.json [--block 120 --delta 20 --kcol 200 --time 300
        --sub-time 15 --threads 1 --procs 4 --seed 0 --solver highs]
"""
import argparse
import json
import multiprocessing as mp
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402

try:
    from numba import njit
except Exception:  # pragma: no cover
    def njit(*a, **k):
        def w(f):
            return f
        return w if not (a and callable(a[0])) else a[0]


@njit(cache=True)
def _enum(sz, lb, hi, cap, order):
    """Sous-ensembles de 1..3 indices (dans sz trié croissant) de somme dans [lb, hi].
    Retourne (ia, ib, ic, exc), -1 pour les positions absentes. Paires et triplets plafonnés à `cap` chacun ;
    triplets énumérés dans l'ordre `order` des premiers éléments."""
    n = sz.shape[0]
    cap_tot = cap * 2 + n + 4
    out_a = np.empty(cap_tot, np.int32)
    out_b = np.empty(cap_tot, np.int32)
    out_c = np.empty(cap_tot, np.int32)
    exc = np.empty(cap_tot, np.int64)
    m = 0
    for i in range(n):
        if sz[i] > hi:
            break
        if sz[i] >= lb:
            out_a[m] = i; out_b[m] = -1; out_c[m] = -1; exc[m] = sz[i] - lb; m += 1
    cnt = 0
    j = n - 1
    for i in range(n):
        if cnt >= cap:
            break
        while j > i and sz[i] + sz[j] > hi:
            j -= 1
        jj = j
        while jj > i and sz[i] + sz[jj] >= lb:
            if cnt >= cap:
                break
            out_a[m] = i; out_b[m] = jj; out_c[m] = -1; exc[m] = sz[i] + sz[jj] - lb; m += 1; cnt += 1
            jj -= 1
        if sz[i] * 2 > hi:
            break
    cnt = 0
    for oi in range(n):
        i = order[oi]
        if cnt >= cap:
            break
        if sz[i] * 3 > hi:
            continue
        k = n - 1
        for j in range(i + 1, n):
            s2 = sz[i] + sz[j]
            if s2 + sz[j] > hi:
                break
            while k > j and s2 + sz[k] > hi:
                k -= 1
            kk = k
            while kk > j and s2 + sz[kk] >= lb:
                if cnt >= cap:
                    break
                out_a[m] = i; out_b[m] = j; out_c[m] = kk; exc[m] = s2 + sz[kk] - lb; m += 1; cnt += 1
                kk -= 1
            if cnt >= cap:
                break
    return out_a[:m], out_b[:m], out_c[:m], exc[:m]


def slots_of(inst, sol):
    """Créneaux de la solution : liste de dict(m, t, lb, ub, free_only, pack=[ids])."""
    src = {s for s, _ in sol["modelMappings"]}
    cov = {(t, inst.reqs[s][0][0]) for s, t in sol["modelMappings"]}
    byd = {}
    for d, m in sol["dataMappings"]:
        byd.setdefault(m, []).append(d)
    slots = []
    for m, ds in byd.items():
        full = m not in src and not any(inst.ds[d][2] for d in ds) and not any((m, t) in cov for t in range(4))
        fill = {}
        for d in ds:
            fill.setdefault(inst.ds[d][0], []).append(d)
        for t, dl in fill.items():
            lb, ub = next((lb, ub) for tt, lb, ub in inst.reqs[m] if tt == t)
            slots.append({"m": m, "t": t, "lb": lb, "ub": ub, "free_only": full, "pack": sorted(dl)})
    return slots


def build_columns(inst, slots, sel, cur, pool, delta, kcol, rng):
    """Colonnes pour les créneaux `sel` (indices dans slots), paquets courants `cur` {si: [ids]}, datasets
    autorisés `pool` (ids). Retourne liste (si, tuple ids, coût) ; inclut toujours le paquet courant."""
    allds = sorted((inst.ds[d][1], d) for d in pool)
    freeds = [(s, d) for s, d in allds if not inst.ds[d][2]]
    arrs = {}
    for key, lst in (("all", allds), ("free", freeds)):
        arrs[key] = (np.array([s for s, _ in lst], np.int64), np.array([d for _, d in lst], np.int64))
    cols = []
    stat = {"sing": 0, "pair": 0, "tri": 0, "var": 0, "cur": 0, "widened": 0}
    for si in sel:
        sl = slots[si]
        sz, ids = arrs["free" if sl["free_only"] else "all"]
        lb, ub = sl["lb"], sl["ub"]
        seen = set()
        pack = tuple(cur[si])
        cost0 = sum(inst.ds[d][1] for d in pack)
        cols.append((si, pack, cost0)); seen.add(pack); stat["cur"] += 1
        if len(pack) >= 2:  # variantes : un retiré, un remplacé
            for r in pack:
                s_r = cost0 - inst.ds[r][1]
                if s_r >= lb:
                    key = tuple(x for x in pack if x != r)
                    if key not in seen:
                        cols.append((si, key, s_r)); seen.add(key); stat["var"] += 1
                lo_, hi_ = lb - s_r, min(ub, lb + delta) - s_r
                a, b = np.searchsorted(sz, lo_), np.searchsorted(sz, hi_, side="right")
                for p in range(a, min(b, a + 30)):
                    d = int(ids[p])
                    if d in pack:
                        continue
                    key = tuple(sorted([x for x in pack if x != r] + [d]))
                    if key not in seen:
                        cols.append((si, key, s_r + int(sz[p]))); seen.add(key); stat["var"] += 1
        if len(sz) == 0:
            continue
        d_ = delta
        order = np.array(rng.permutation(len(sz)), np.int64)
        while True:
            hi = min(ub, lb + d_)
            ia, ib, ic, exc = _enum(sz, lb, hi, kcol * 3, order)
            found = list(zip(exc.tolist(), ia.tolist(), ib.tolist(), ic.tolist()))
            if len(found) >= min(kcol, 30) or hi >= ub:
                break
            d_ *= 3; stat["widened"] += 1
        found.sort()
        for e, a, b, c in found[:kcol]:
            key = tuple(sorted(int(ids[x]) for x in (a, b, c) if x >= 0))
            if key in seen:
                continue
            seen.add(key)
            cols.append((si, key, lb + e))
            stat["sing" if b < 0 else ("pair" if c < 0 else "tri")] += 1
    return cols, stat


def solve_cols(cols, cur, tlimit, threads, seed, solver, verbose, lbs=None, conc=0.0):
    """Set-partitioning sur `cols` avec hint = cur. Retourne ({si: key}, coût, borne, statut).
    conc > 0 (HiGHS) : 2e phase à consommation fixée au mieux trouvé, max Σ min(excès, 3000)² (concentre le
    gaspillage sur peu de créneaux pour qu'un dataset entier devienne libérable au tour suivant)."""
    sidx = sorted({si for si, _, _ in cols})
    curset = {(si, tuple(cur[si])) for si in sidx}
    hint = np.array([1.0 if (si, key) in curset else 0.0 for si, key, _ in cols])
    cost = np.array([c for _, _, c in cols], float)
    if solver == "cp":
        from ortools.sat.python import cp_model
        m = cp_model.CpModel()
        x = [m.NewBoolVar(f"x{c}") for c in range(len(cols))]
        byslot, byds = {}, {}
        for c, (si, key, cst) in enumerate(cols):
            byslot.setdefault(si, []).append(x[c])
            for d in key:
                byds.setdefault(d, []).append(x[c])
        for lst in byslot.values():
            m.AddExactlyOne(lst)
        for lst in byds.values():
            if len(lst) > 1:
                m.AddAtMostOne(lst)
        m.Minimize(sum(int(cost[c]) * x[c] for c in range(len(cols))))
        for c in range(len(cols)):
            m.AddHint(x[c], int(hint[c] > 0.5))
        sv = cp_model.CpSolver()
        sv.parameters.max_time_in_seconds = float(tlimit)
        sv.parameters.num_workers = int(threads)
        sv.parameters.random_seed = int(seed)
        sv.parameters.log_search_progress = bool(verbose)
        st = sv.Solve(m)
        if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            res = {si: key for c, (si, key, _) in enumerate(cols) if sv.Value(x[c])}
            return res, int(sv.ObjectiveValue()), float(sv.BestObjectiveBound()), sv.StatusName(st)
        return {}, 0, 0.0, sv.StatusName(st)
    import highspy
    srow = {si: i for i, si in enumerate(sidx)}
    dids = sorted({d for _, key, _ in cols for d in key})
    drow = {d: len(sidx) + i for i, d in enumerate(dids)}
    ncol, nrow = len(cols), len(sidx) + len(dids)
    start = np.zeros(ncol + 1, np.int32); index = []; value = []
    for c, (si, key, cst) in enumerate(cols):
        index.append(srow[si]); value.append(1.0)
        for d in key:
            index.append(drow[d]); value.append(1.0)
        start[c + 1] = len(index)
    h = highspy.Highs()
    h.setOptionValue("output_flag", bool(verbose))
    h.setOptionValue("threads", int(threads))
    h.setOptionValue("time_limit", float(tlimit))
    h.setOptionValue("mip_rel_gap", 0.0)
    h.setOptionValue("random_seed", int(seed))
    lp = highspy.HighsLp()
    lp.num_col_ = ncol; lp.num_row_ = nrow
    lp.col_cost_ = cost; lp.col_lower_ = np.zeros(ncol); lp.col_upper_ = np.ones(ncol)
    lp.row_lower_ = np.concatenate([np.ones(len(sidx)), np.zeros(len(dids))]); lp.row_upper_ = np.ones(nrow)
    lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    lp.a_matrix_.start_ = start; lp.a_matrix_.index_ = np.array(index, np.int32); lp.a_matrix_.value_ = np.array(value)
    lp.integrality_ = [highspy.HighsVarType.kInteger] * ncol
    h.passModel(lp)
    s0 = highspy.HighsSolution(); s0.col_value = list(hint); h.setSolution(s0)
    h.run()
    info = h.getInfo()
    status = h.modelStatusToString(h.getModelStatus())
    if not info.primal_solution_status:
        return {}, 0, 0.0, status
    xs = np.array(h.getSolution().col_value)
    if len(xs) != ncol:
        return {}, 0, 0.0, status
    x = np.round(xs)
    obj1 = int(cost[x > 0.5].sum()); bound = float(info.mip_dual_bound)
    if conc > 0 and lbs is not None:
        exc = np.array([min(c - lbs[si], 3000) for si, _, c in cols], float)
        h.addRow(-1e30, float(obj1) + 0.5, ncol, np.arange(ncol, dtype=np.int32), cost)
        h.changeColsCost(ncol, np.arange(ncol, dtype=np.int32), -(exc ** 2) / 1e4)
        h.setOptionValue("time_limit", float(conc))
        s1 = highspy.HighsSolution(); s1.col_value = list(x); h.setSolution(s1)
        h.run()
        if h.getInfo().primal_solution_status:
            xs2 = np.array(h.getSolution().col_value)
            if len(xs2) == ncol:
                x2 = np.round(xs2)
                if int(cost[x2 > 0.5].sum()) <= obj1:
                    x = x2
    res = {si: key for c, (si, key, _) in enumerate(cols) if x[c] > 0.5}
    return res, int(cost[x > 0.5].sum()), bound, status


def check_apply(inst, slots, cur, res, sidx):
    """Vérifie une solution de sous-problème (fenêtres, copyright, datasets uniques) et renvoie le nouveau cur ou None."""
    used = set()
    for si in sidx:
        if si not in res:
            return None
        key = res[si]
        sl = slots[si]
        s = sum(inst.ds[d][1] for d in key)
        if not (sl["lb"] <= s <= sl["ub"]) or any(inst.ds[d][0] != sl["t"] for d in key):
            return None
        if sl["free_only"] and any(inst.ds[d][2] for d in key):
            return None
        if any(d in used for d in key):
            return None
        used.update(key)
    other = set()
    for si, p in cur.items():
        if si not in sidx:
            other.update(p)
    if used & other:
        return None
    new = dict(cur)
    for si in sidx:
        new[si] = sorted(res[si])
    return new


def solve_type(args):
    """Un type : boucle de blocs (ou MIP global). Retourne (t, {si: pack}, infos)."""
    k, sol, t, delta, kcol, tlimit, sub_time, block, threads, seed, verbose, solver, conc = args
    t0 = time.time()
    inst = Instance(k)
    slots = slots_of(inst, sol)
    rng = np.random.RandomState(seed * 7 + t + 1)
    tslots = [si for si, s in enumerate(slots) if s["t"] == t]
    cur = {si: list(slots[si]["pack"]) for si in tslots}
    usedds = {d for si in tslots for d in cur[si]}
    unused = [d for d, (tt, _, _) in enumerate(inst.ds) if tt == t and d not in usedds]
    cost_of = lambda c: sum(sum(inst.ds[d][1] for d in p) for p in c.values())
    cur_cost = cost_of(cur)
    log = []
    nit = nimp = 0
    if block <= 0:
        pool = [d for d, (tt, _, _) in enumerate(inst.ds) if tt == t]
        cols, stat = build_columns(inst, slots, tslots, cur, pool, delta, kcol, rng)
        res, c_new, bound, status = solve_cols(cols, cur, tlimit, threads, seed, solver, verbose)
        new = check_apply(inst, slots, cur, res, tslots) if res else None
        if new is not None and cost_of(new) < cur_cost:
            cur = new
        log.append(f"global {len(cols)} col. {stat} {status} borne {bound:.0f}")
        nit = 1
    else:
        waste = lambda si: sum(inst.ds[d][1] for d in cur[si]) - slots[si]["lb"]
        while time.time() - t0 < tlimit:
            nit += 1
            if rng.rand() < 0.5:  # bloc aléatoire
                sel = list(rng.choice(tslots, size=min(block, len(tslots)), replace=False))
            else:  # bloc biaisé vers les créneaux les plus gaspilleurs
                w = np.array([waste(si) + 1.0 for si in tslots], float)
                sel = list(rng.choice(tslots, size=min(block, len(tslots)), replace=False, p=w / w.sum()))
            pool = sorted({d for si in sel for d in cur[si]} | set(unused))
            cols, stat = build_columns(inst, slots, sel, cur, pool, delta, kcol, rng)
            lbs = {si: slots[si]["lb"] for si in sel}
            res, c_new, bound, status = solve_cols(cols, cur, sub_time, threads, seed + nit, solver, verbose, lbs, conc)
            new = check_apply(inst, slots, cur, res, sel) if res else None
            if new is not None and cost_of(new) <= cost_of(cur):
                if cost_of(new) == cost_of(cur):
                    cur = new  # même consommation, gaspillage concentré
                    continue
                gain = cost_of(cur) - cost_of(new)
                cur = new
                usedds = {d for si in tslots for d in cur[si]}
                unused = [d for d, (tt, _, _) in enumerate(inst.ds) if tt == t and d not in usedds]
                nimp += 1
                log.append(f"it {nit} t={time.time() - t0:.0f}s bloc {len(sel)} {len(cols)} col. -{gain} "
                           f"({status}, borne {bound:.0f}) libres {len(unused)}")
    new_cost = cost_of(cur)
    infos = dict(t=t, slots=len(tslots), cur=cur_cost, new=int(new_cost), it=nit, imp=nimp, log=log,
                 unused=len(unused), time=round(time.time() - t0, 1))
    return t, cur, infos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("--start", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--delta", type=int, default=20)
    ap.add_argument("--kcol", type=int, default=200)
    ap.add_argument("--time", type=float, default=300, help="budget par type (s)")
    ap.add_argument("--sub-time", type=float, default=15, help="limite par sous-MIP (mode blocs)")
    ap.add_argument("--block", type=int, default=120, help="créneaux par bloc (0 = MIP global)")
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--types", type=int, nargs="*", default=[0, 1, 2, 3])
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--solver", choices=["highs", "cp"], default="highs")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--conc", type=float, default=5.0, help="durée (s) de la 2e phase de concentration (0 = off)")
    a = ap.parse_args()
    t0 = time.time()
    k = a.instance
    inst = Instance(k)
    with open(a.start) as f:
        sol = json.load(f)
    from save_if_better import evaluate
    s_start, ok, msg = evaluate(k, json.dumps(sol), inst.txt)
    slots = slots_of(inst, sol)
    waste0 = sum(sum(inst.ds[d][1] for d in s["pack"]) - s["lb"] for s in slots)
    print(f"inst {k} départ {a.start} : score {s_start} valide={ok}, {len(slots)} créneaux, gaspillage {waste0} "
          f"(seed {a.seed}, bloc {a.block}, delta {a.delta}, kcol {a.kcol}, {a.solver})", flush=True)
    jobs = [(k, sol, t, a.delta, a.kcol, a.time, a.sub_time, a.block, a.threads, a.seed, a.verbose, a.solver, a.conc)
            for t in a.types]
    if a.procs > 1 and len(jobs) > 1:
        with mp.get_context("fork").Pool(min(a.procs, len(jobs))) as pool:
            results = pool.map(solve_type, jobs)
    else:
        results = [solve_type(j) for j in jobs]
    newpack = {}
    for t, res, info in results:
        newpack.update(res)
        print(f"  type {t}: {info['slots']} créneaux, {info['it']} it., {info['imp']} améliorations, {info['time']}s : "
              f"conso {info['cur']} -> {info['new']} (gain {info['cur'] - info['new']}), datasets libres {info['unused']}",
              flush=True)
        if not a.quiet:
            for line in info["log"][-8:]:
                print("     " + line, flush=True)
    dm = []
    for si, s in enumerate(slots):
        for d in newpack.get(si, s["pack"]):
            dm.append([int(d), int(s["m"])])
    out = {"dataMappings": dm, "modelMappings": sol["modelMappings"]}
    txt = json.dumps(out, separators=(",", ":"))
    s_new, ok2, msg2 = evaluate(k, txt, inst.txt)
    waste1 = sum(sum(inst.ds[d][1] for d in newpack.get(si, s["pack"])) - s["lb"] for si, s in enumerate(slots))
    tot = sum(s for _, s, _ in inst.ds)
    print(f"résultat : score {s_new} valide={ok2} {msg2 if not ok2 else ''}; gaspillage {waste0} -> {waste1} "
          f"({waste0 / tot * 100:.3f} % -> {waste1 / tot * 100:.3f} % de l'offre) ; datasets utilisés "
          f"{len(dm)}/{len(inst.ds)} ; {time.time() - t0:.0f}s", flush=True)
    if ok2 and s_new >= s_start:
        with open(a.out, "w") as f:
            f.write(txt)
        print(f"écrit {a.out}", flush=True)
    else:
        print("solution rejetée (invalide ou score inférieur) : rien d'écrit", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
