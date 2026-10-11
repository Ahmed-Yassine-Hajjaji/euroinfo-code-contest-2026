#!/usr/bin/env python3
"""Ré-appariement exact « paquets ↔ modèles » (MIP HiGHS).

Idée : la meilleure solution connue contient des paquets (groupes de datasets d'un même type affectés à un besoin ou
à un générateur). Un paquet de somme S peut servir N'IMPORTE QUEL besoin (m, t) avec lb ≤ S ≤ ub (libre seulement
pour un modèle plein tarif). On ré-optimise exactement les rôles (f, h, y, z) et l'affectation des paquets
(+ chaque dataset seul comme paquet) : énergie, un dataset au plus une fois, comptage générateurs/cibles par type.
La solution est réalisable par construction (les paquets sont des ensembles valides).

Usage : python src/rematch.py <k> [--start best/instance_k.json] [--time 600] [--theta 60] [--save] [--out f]
  --theta : seuil de coût réduit LP (points) pour restreindre les modèles candidats (0 = tous les modèles).
"""
import argparse
import json
import os
import sys
import time

import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds
from scipy.sparse import coo_matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402


def packages_from_solution(inst, sol, singletons=True, extra=(), subsets=False):
    """Paquets = (type, somme, libre?, [datasets]). Ceux de la solution (+ leurs sous-ensembles si subsets)
    + chaque dataset seul (si singletons)."""
    from itertools import combinations
    pk = {}
    for d, m in sol["dataMappings"]:
        pk.setdefault((m, inst.ds[d][0]), []).append(d)
    packs = []
    seen = set()

    def add(ds):
        key = tuple(sorted(ds))
        if key in seen:
            return
        seen.add(key)
        packs.append((inst.ds[ds[0]][0], sum(inst.ds[d][1] for d in ds), not any(inst.ds[d][2] for d in ds), list(ds)))

    for (m, t), ds in pk.items():
        add(ds)
        if subsets and 2 <= len(ds) <= 6:
            for r in range(1, len(ds)):
                for sub in combinations(ds, r):
                    add(list(sub))
    for p in extra:
        add(list(p))
    if singletons:
        for d in range(len(inst.ds)):
            add([d])
    return packs


def generate_packages(inst, sol, K, delta, rng, windows_extra=()):
    """Génération de colonnes par échantillonnage : pour chaque fenêtre (type, lb, ub, copyright autorisé) des
    créneaux de la solution (+ windows_extra), K sous-ensembles de 1 à 3 datasets de somme dans [lb, min(ub, lb+delta)].
    Les datasets peuvent être utilisés ailleurs : le MIP arbitre (ligne « dataset <= 1 fois »)."""
    from bisect import bisect_left, bisect_right
    pools = {}
    for d, (t, sz, c) in enumerate(inst.ds):
        pools.setdefault((t, True), []).append((sz, d))
        if not c:
            pools.setdefault((t, False), []).append((sz, d))
    for v in pools.values():
        v.sort()
    src = {s_ for s_, _ in sol["modelMappings"]}
    cov = {(tg, inst.reqs[s_][0][0]) for s_, tg in sol["modelMappings"]}
    pk = {}
    for d, m in sol["dataMappings"]:
        pk.setdefault((m, inst.ds[d][0]), []).append(d)
    defiled = {}
    for (m, t), ds in pk.items():
        defiled[m] = defiled.get(m, False) or any(inst.ds[d][2] for d in ds) or any((m, tt) in cov for tt in range(4))
    windows = set(windows_extra)
    for (m, t), ds in pk.items():
        lb, ub = next((lb, ub) for tt, lb, ub in inst.reqs[m] if tt == t)
        windows.add((t, lb, ub, True if m in src else bool(defiled.get(m))))
    out = []
    for (t, lb, ub, cr) in windows:
        pool = pools.get((t, cr), [])
        if not pool:
            continue
        hi = min(ub, lb + delta)
        sizes = [x[0] for x in pool]
        # singles
        a, b = bisect_left(sizes, lb), bisect_right(sizes, hi)
        if b > a:
            for j in rng.sample(range(a, b), min(b - a, max(1, K // 3))):
                out.append([pool[j][1]])
        n = len(pool)
        # paires / triplets
        for _ in range(3 * K):
            k = rng.choice((2, 2, 3))
            chosen = [rng.randrange(n) for _ in range(k - 1)]
            if len(set(chosen)) < k - 1:
                continue
            ssum = sum(pool[j][0] for j in chosen)
            if ssum >= hi:
                continue
            a, b = bisect_left(sizes, lb - ssum), bisect_right(sizes, hi - ssum)
            cands = [j for j in range(a, min(b, a + 50)) if j not in chosen]
            if not cands:
                continue
            j = rng.choice(cands)
            out.append([pool[i][1] for i in chosen] + [pool[j][1]])
    return out


def candidate_models(inst, lp, theta):
    """Modèles / générateurs candidats par coût réduit LP (>= -theta). theta <= 0 : tous."""
    nm = len(inst.value)
    if theta <= 0 or lp is None:
        return set(range(nm)), {m for m in range(nm) if inst.gen_ok[m]}
    pe = lp["dual_energy"] / inst.cap
    pf, pt, pg = lp["dual_free"], lp["dual_total"], lp["dual_gen"]
    M, G = set(), set()
    for m in range(nm):
        e = pe * inst.energy[m]
        rq = inst.reqs[m]
        rf = inst.value[m] - e - sum((pf[t] + pt[t]) * lb for t, lb, ub in rq) if all(lb <= ub for _, lb, ub in rq) else -1e18
        rh = inst.value[m] // 2 - e - sum(min(pt[t] * lb, pg[t]) if lb <= ub else pg[t] for t, lb, ub in rq)
        if max(rf, rh) >= -theta:
            M.add(m)
        if inst.gen_ok[m]:
            t, lb, _ = rq[0]
            if -e - pt[t] * lb + pg[t] >= -theta:
                G.add(m)
    return M, G


def reduced_costs(inst, lp):
    """Coût réduit LP (points) du meilleur rôle entraîné de chaque modèle, et du rôle générateur."""
    nm = len(inst.value)
    if lp is None:
        return [0.0] * nm, [0.0] * nm
    pe = lp["dual_energy"] / inst.cap
    pf, pt, pg = lp["dual_free"], lp["dual_total"], lp["dual_gen"]
    rm, rg = [], []
    for m in range(nm):
        e = pe * inst.energy[m]
        rq = inst.reqs[m]
        rf = inst.value[m] - e - sum((pf[t] + pt[t]) * lb for t, lb, ub in rq) if all(lb <= ub for _, lb, ub in rq) else -1e18
        rh = inst.value[m] // 2 - e - sum(min(pt[t] * lb, pg[t]) if lb <= ub else pg[t] for t, lb, ub in rq)
        rm.append(max(rf, rh))
        if inst.gen_ok[m]:
            t, lb, _ = rq[0]
            rg.append(-e - pt[t] * lb + pg[t])
        else:
            rg.append(-1e18)
    return rm, rg


def build_and_solve(inst, packs, M, G, tlimit, verbose=True, gap=0.0, kbest=0, rc=None, keep=(), hint=None, lex_time=0.0,
                    cg_rounds=0, cg_lp_time=600.0, cg_alpha=0.0, cg_split=1, cg_max_cols=0, cg_min_gain=1e-6):
    """kbest > 0 : pour chaque paquet, on ne garde que les kbest besoins compatibles de meilleur coût réduit
    (rc = (rc_modèle, rc_générateur)), plus les affectations de la solution de départ (keep = {(paquet, cible)})."""
    nm = len(inst.value)
    t0 = time.time()
    rcm, rcg = rc if rc else ([0.0] * nm, [0.0] * nm)
    col = 0
    obj, lo, hi = [], [], []
    fi, hi_, yi, zi = {}, {}, {}, {}

    def newcol(c, u=1.0):
        nonlocal col
        obj.append(c); lo.append(0.0); hi.append(u); col += 1
        return col - 1

    for m in sorted(M):
        feas = all(lb <= ub for _, lb, ub in inst.reqs[m])
        fi[m] = newcol(-inst.value[m], 1.0 if feas else 0.0)
        hi_[m] = newcol(-(inst.value[m] // 2))
        for t, lb, ub in inst.reqs[m]:
            zi[(m, t)] = newcol(0.0)
    for g in sorted(G):
        yi[g] = newcol(0.0)
    nrole = col
    # compatibilité paquets -> besoins (par type, vectorisé)
    needs = [[] for _ in range(4)]
    for m in M:
        for t, lb, ub in inst.reqs[m]:
            if lb <= ub:
                needs[t].append((lb, ub, m))
    gens = [[] for _ in range(4)]
    for g in G:
        t, lb, ub = inst.reqs[g][0]
        gens[t].append((lb, ub, g))
    rows, cols, vals = [], [], []
    rhs_lo, rhs_hi = [], []
    r = 0
    # lignes de rôles
    R1 = {}
    for m in sorted(M | G):
        R1[m] = r; rhs_lo.append(-np.inf); rhs_hi.append(1.0)
        if m in fi:
            rows += [r, r]; cols += [fi[m], hi_[m]]; vals += [1, 1]
        if m in yi:
            rows.append(r); cols.append(yi[m]); vals.append(1)
        r += 1
    R2, R3 = {}, {}
    for m in sorted(M):
        for t, lb, ub in inst.reqs[m]:
            R2[(m, t)] = r; rhs_lo.append(0.0); rhs_hi.append(0.0)
            rows += [r, r, r]; cols += [zi[(m, t)], fi[m], hi_[m]]; vals += [1, -1, -1]; r += 1
            R3[(m, t)] = r; rhs_lo.append(-np.inf); rhs_hi.append(0.0)
            rows += [r, r]; cols += [zi[(m, t)], hi_[m]]; vals += [1, -1]; r += 1
    R4 = {}
    for g in sorted(G):
        R4[g] = r; rhs_lo.append(0.0); rhs_hi.append(0.0)
        rows.append(r); cols.append(yi[g]); vals.append(-1); r += 1
    R5 = list(range(r, r + 4)); r += 4
    rhs_lo += [-np.inf] * 4; rhs_hi += [0.0] * 4
    for (m, t), c in zi.items():
        rows.append(R5[t]); cols.append(c); vals.append(1)
    for g, c in yi.items():
        rows.append(R5[inst.reqs[g][0][0]]); cols.append(c); vals.append(-1)
    RD = list(range(r, r + len(inst.ds))); r += len(inst.ds)
    rhs_lo += [-np.inf] * len(inst.ds); rhs_hi += [1.0] * len(inst.ds)
    RE = r; r += 1; rhs_lo.append(-np.inf); rhs_hi.append(1.0 - 2e-7)  # marge pour la tolérance du solveur
    for m in M:
        rows += [RE, RE]; cols += [fi[m], hi_[m]]; vals += [inst.energy[m] / inst.cap] * 2
    for g in G:
        rows.append(RE); cols.append(yi[g]); vals.append(inst.energy[g] / inst.cap)
    # colonnes d'affectation
    acol = []  # (col, pack index, kind, key)
    for t in range(4):
        L = np.array([x[0] for x in needs[t]]); U = np.array([x[1] for x in needs[t]]); Mn = [x[2] for x in needs[t]]
        Lg = np.array([x[0] for x in gens[t]]); Ug = np.array([x[1] for x in gens[t]]); Gg = [x[2] for x in gens[t]]
        RCn = np.array([rcm[m] for m in Mn]); RCg = np.array([rcg[g] for g in Gg])
        for pi, (tt, S, free, ds) in enumerate(packs):
            if tt != t:
                continue
            keep_p = keep.get(tuple(sorted(ds)), set()) if kbest else set()
            if len(L):
                js = np.nonzero((L <= S) & (S <= U))[0]
                if kbest and len(js) > kbest:
                    js = js[np.argsort(-RCn[js])[:kbest]]
                    js = set(js.tolist()) | {j for j in range(len(Mn)) if Mn[j] in keep_p and L[j] <= S <= U[j]}
                for j in js:
                    m = Mn[j]
                    c = newcol(0.0)
                    acol.append((c, pi, 0, (m, t)))
                    rows.append(R2[(m, t)]); cols.append(c); vals.append(1)
                    if not free:
                        rows.append(R3[(m, t)]); cols.append(c); vals.append(1)
                    for d in ds:
                        rows.append(RD[d]); cols.append(c); vals.append(1)
            if len(Lg):
                js = np.nonzero((Lg <= S) & (S <= Ug))[0]
                if kbest and len(js) > kbest:
                    js = js[np.argsort(-RCg[js])[:kbest]]
                    js = set(js.tolist()) | {j for j in range(len(Gg)) if Gg[j] in keep_p and Lg[j] <= S <= Ug[j]}
                for j in js:
                    g = Gg[j]
                    c = newcol(0.0)
                    acol.append((c, pi, 1, g))
                    rows.append(R4[g]); cols.append(c); vals.append(1)
                    for d in ds:
                        rows.append(RD[d]); cols.append(c); vals.append(1)
    def assemble():
        return coo_matrix((np.array(vals, dtype=float), (np.array(rows), np.array(cols))), shape=(r, col)).tocsc()

    A = assemble()
    if verbose:
        print(f"  modèle : {col} colonnes ({nrole} rôles, {len(acol)} affectations), {r} lignes, "
              f"{A.nnz} non-zéros, construit en {time.time()-t0:.0f}s", flush=True)
    import highspy

    def make_highs(A, integer):
        h = highspy.Highs()
        h.setOptionValue("output_flag", False)
        h.setOptionValue("threads", int(os.environ.get("HIGHS_THREADS", "1")))
        lp = highspy.HighsLp()
        lp.num_col_ = col; lp.num_row_ = r
        lp.col_cost_ = np.array(obj, dtype=float); lp.col_lower_ = np.array(lo); lp.col_upper_ = np.array(hi)
        lp.row_lower_ = np.array(rhs_lo); lp.row_upper_ = np.array(rhs_hi)
        lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
        lp.a_matrix_.start_ = A.indptr.astype(np.int32); lp.a_matrix_.index_ = A.indices.astype(np.int32)
        lp.a_matrix_.value_ = A.data
        if integer:
            lp.integrality_ = [highspy.HighsVarType.kInteger] * col
        h.passModel(lp)
        return h

    # ----- génération de colonnes : LP relâchée -> duaux -> meilleur paquet par besoin (sac à dos exact) -----
    existing = {(tuple(sorted(packs[pi][3])), kind, key) for c, pi, kind, key in acol}
    y_prev = None
    for rnd in range(cg_rounds):
        t1 = time.time()
        hl = make_highs(A, False)
        hl.setOptionValue("time_limit", float(cg_lp_time))
        hl.run()
        sl = hl.getSolution()
        if len(sl.row_dual) != r:
            print("  cg : LP sans duaux, arrêt", flush=True); break
        y = np.array(sl.row_dual)
        lpval = -float(np.dot(np.array(obj), np.array(sl.col_value)))
        if cg_alpha > 0 and y_prev is not None:  # stabilisation (lissage de Wentges) : prix = mélange avec les précédents
            y = cg_alpha * y_prev + (1 - cg_alpha) * y
        y_prev = y
        yD = y[RD]  # duaux des lignes « dataset <= 1 fois » (<= 0)
        Cmax = 0
        for m in M:
            for t, lb, ub in inst.reqs[m]:
                if lb <= ub: Cmax = max(Cmax, ub)
        for g in G:
            Cmax = max(Cmax, inst.reqs[g][0][2])
        Cmax = min(Cmax, 200000)
        tables = {}
        for t in range(4):
            for cr in (False, True):
                items = [(d, sz) for d, (tt, sz, c) in enumerate(inst.ds) if tt == t and (cr or not c) and sz <= Cmax]
                best = np.full(Cmax + 1, -np.inf); best[0] = 0.0
                choice = []
                for d, sz in items:
                    cand = best[:-sz] + yD[d]
                    better = cand > best[sz:]
                    best[sz:] = np.where(better, cand, best[sz:])
                    choice.append(np.packbits(better))
                tables[(t, cr)] = (items, best, choice)

        def rebuild(t, cr, c):
            items, best, choice = tables[(t, cr)]
            out = []
            for i in range(len(items) - 1, -1, -1):
                d, sz = items[i]
                if c >= sz and (choice[i][(c - sz) >> 3] >> (7 - ((c - sz) & 7))) & 1:
                    out.append(d); c -= sz
                    if c == 0: break
            return out if c == 0 else None

        def best_window(t, cr, lb, ub):
            best = tables[(t, cr)][1]
            seg = best[lb:min(ub, Cmax) + 1]
            if not len(seg): return -np.inf, None
            j = int(np.argmax(seg))
            return float(seg[j]), lb + j

        def windows(lb, ub):
            # fenêtre entière + cg_split sous-fenêtres (colonnes diversifiées par somme)
            yield lb, ub
            if cg_split > 1 and ub > lb:
                w = (ub - lb + 1) // cg_split
                for q in range(cg_split):
                    yield lb + q * w, (lb + (q + 1) * w - 1 if q < cg_split - 1 else ub)

        def add_col(ds, c_, kind, key, row_main, row_cr):
            nonlocal col
            pi = len(packs); packs.append((inst.ds[ds[0]][0], c_, not any(inst.ds[d][2] for d in ds), list(ds)))
            c = newcol(0.0); acol.append((c, pi, kind, key))
            rows.append(row_main); cols.append(c); vals.append(1)
            if row_cr is not None and not packs[pi][2]:
                rows.append(row_cr); cols.append(c); vals.append(1)
            for d in ds:
                rows.append(RD[d]); cols.append(c); vals.append(1)

        added = 0; gsum = 0.0; gmax = 0.0
        cand = []  # (gain, t, cr, c_, kind, key)
        for m in M:
            for t, lb, ub in inst.reqs[m]:
                if lb > ub: continue
                for cr in (False, True):
                    gain = y[R2[(m, t)]] + (y[R3[(m, t)]] if cr else 0.0)
                    for wl, wu in windows(lb, ub):
                        v, c_ = best_window(t, cr, wl, wu)
                        if c_ is None or gain + v <= cg_min_gain: continue
                        gsum += gain + v; gmax = max(gmax, gain + v)
                        cand.append((gain + v, t, cr, c_, 0, (m, t)))
        for g in G:
            t, lb, ub = inst.reqs[g][0]
            for wl, wu in windows(lb, ub):
                v, c_ = best_window(t, True, wl, wu)
                if c_ is None or y[R4[g]] + v <= cg_min_gain: continue
                gsum += y[R4[g]] + v; gmax = max(gmax, y[R4[g]] + v)
                cand.append((y[R4[g]] + v, t, True, c_, 1, g))
        cand.sort(key=lambda x: -x[0])
        for gain, t, cr, c_, kind, key in cand:
            if cg_max_cols and added >= cg_max_cols: break
            ds = rebuild(t, cr, c_)
            if ds is None: continue
            k2 = (tuple(sorted(ds)), kind, key)
            if k2 in existing: continue
            existing.add(k2)
            if kind == 0:
                add_col(ds, c_, 0, key, R2[key], R3[key])
            else:
                add_col(ds, c_, 1, key, R4[key], None)
            added += 1
        A = assemble()
        if verbose:
            print(f"  cg tour {rnd+1} : LP {lpval:.1f}, {added} colonnes ajoutées ({col} au total), gain max {gmax:.2f} somme {gsum:.1f}, en {time.time()-t1:.0f}s", flush=True)
        if added == 0: break

    # hint = solution de départ (rôles + affectations de ses paquets)
    x0 = np.zeros(col)
    if hint is not None:
        trained, defiled, cov, gens_on, cur = hint
        for m in M:
            if m in trained:
                x0[hi_[m] if defiled[m] else fi[m]] = 1.0
                for t, _, _ in inst.reqs[m]:
                    if (m, t) in cov:
                        x0[zi[(m, t)]] = 1.0
        for g in G:
            if g in gens_on:
                x0[yi[g]] = 1.0
        nh = 0
        for c, pi, kind, key in acol:
            tgt = key[0] if kind == 0 else key
            if cur.get((tuple(sorted(packs[pi][3])), tgt, kind)):
                x0[c] = 1.0; nh += 1
        Ax = A @ x0
        bad = np.nonzero((Ax > np.array(rhs_hi) + 1e-9) | (Ax < np.array(rhs_lo) - 1e-9))[0]
        if verbose:
            cat = {"R1": set(R1.values()), "R2": set(R2.values()), "R3": set(R3.values()), "R4": set(R4.values()),
                   "R5": set(R5), "RD": set(RD), "RE": {RE}}
            det = {k: sum(1 for b in bad if b in v) for k, v in cat.items()}
            print(f"  hint : {nh} affectations, valeur {-float(np.dot(obj, x0)):.0f}, lignes violées {len(bad)} {det}", flush=True)
            if len(bad) and det["R2"]:
                b = next(b for b in bad if b in cat["R2"]); mt = next(k for k, v in R2.items() if v == b)
                print(f"    ex. R2 {mt}: Ax={Ax[b]} f={x0[fi[mt[0]]]} h={x0[hi_[mt[0]]]} z={x0[zi[mt]]} "
                      f"paquet={[ (pi, packs[pi][3]) for c, pi, kind, key in acol if kind == 0 and key == mt and x0[c] > 0]}", flush=True)
    h = make_highs(A, True)
    h.setOptionValue("output_flag", verbose)
    h.setOptionValue("time_limit", float(tlimit))
    h.setOptionValue("mip_rel_gap", float(gap))
    if hint is not None:
        sol0 = highspy.HighsSolution(); sol0.col_value = list(x0); h.setSolution(sol0)
    h.run()
    info = h.getInfo()
    xs = np.array(h.getSolution().col_value)
    if len(xs) != col or info.primal_solution_status == 0:
        raise RuntimeError(f"HiGHS : pas de solution ({h.modelStatusToString(h.getModelStatus())})")
    x = np.round(xs)
    val = -float(np.dot(obj, x))
    bound = -float(info.mip_dual_bound) if info.mip_dual_bound else None
    if verbose:
        print(f"  MIP : valeur {val:.0f} borne {bound} ({time.time()-t0:.0f}s) {h.modelStatusToString(h.getModelStatus())}", flush=True)
    if lex_time > 0:
        # 2e phase lexicographique : valeur >= val, minimiser la consommation de données (laisser du jeu au LNS)
        cons = np.zeros(col)
        for c, pi, kind, key in acol:
            cons[c] = packs[pi][1]
        cons0 = float(np.dot(cons, x))
        idx = np.nonzero(np.array(obj))[0]
        h.addRow(-np.inf, -(val - 0.5), len(idx), idx.astype(np.int32), np.array(obj)[idx])
        h.changeColsCost(col, np.arange(col, dtype=np.int32), cons)
        h.setOptionValue("time_limit", float(lex_time))
        sol1 = highspy.HighsSolution(); sol1.col_value = list(x); h.setSolution(sol1)
        h.run()
        xs2 = np.array(h.getSolution().col_value)
        if len(xs2) == col and h.getInfo().primal_solution_status != 0:
            x2 = np.round(xs2)
            val2 = -float(np.dot(obj, x2))
            if val2 >= val - 1e-6:
                x = x2; val = val2
            if verbose:
                print(f"  lex : consommation {cons0:.0f} -> {float(np.dot(cons, x)):.0f}, valeur {val:.0f} "
                      f"({time.time()-t0:.0f}s) {h.modelStatusToString(h.getModelStatus())}", flush=True)
    # extraction
    dm, mm = [], []
    f = {m: x[fi[m]] > 0.5 for m in M}
    h = {m: x[hi_[m]] > 0.5 for m in M}
    y = {g: x[yi[g]] > 0.5 for g in G}
    z = {(m, t): x[zi[(m, t)]] > 0.5 for (m, t) in zi}
    for c, pi, kind, key in acol:
        if x[c] > 0.5:
            tgt = key[0] if kind == 0 else key
            dm.extend([d, tgt] for d in packs[pi][3])
    # appariement générateurs <-> cibles par type
    for t in range(4):
        gl = [g for g in sorted(G) if y[g] and inst.reqs[g][0][0] == t]
        tl = [m for (m, tt) in sorted(zi) if tt == t and z[(m, tt)]]
        assert len(tl) <= len(gl), (t, len(tl), len(gl))
        for g, m in zip(gl, tl):
            mm.append([g, m])
        for g in gl[len(tl):]:  # générateurs excédentaires : on les retire (et leurs datasets)
            dm = [[d, mm_] for d, mm_ in dm if mm_ != g]
    roles = {"f": [1.0 if f.get(m) else 0.0 for m in range(nm)], "h": [1.0 if h.get(m) else 0.0 for m in range(nm)],
             "y": [1.0 if y.get(m) else 0.0 for m in range(nm)],
             "z": [[t for t, _, _ in inst.reqs[m] if z.get((m, t))] for m in range(nm)], "value": val, "bound": bound}
    return {"dataMappings": [[int(d), int(m)] for d, m in dm], "modelMappings": [[int(g), int(m)] for g, m in mm]}, roles, val, bound


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("--start", default=None)
    ap.add_argument("--time", type=float, default=600)
    ap.add_argument("--theta", type=float, default=0.0, help="seuil de coût réduit LP (0 = tous les modèles)")
    ap.add_argument("--no-singletons", action="store_true")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--gap", type=float, default=0.0)
    ap.add_argument("--subsets", action="store_true", help="ajoute les sous-ensembles des paquets (2..6 datasets)")
    ap.add_argument("--extra-sols", nargs="*", default=[], help="autres solutions dont on ajoute les paquets (recombinaison)")
    ap.add_argument("--gen", type=int, default=0, help="paquets échantillonnés par fenêtre de créneau (0 = off)")
    ap.add_argument("--delta", type=int, default=150, help="excès max au-dessus de lb des paquets échantillonnés")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--lex", type=float, default=0.0, help="2e phase : min consommation à valeur fixée (durée s, 0 = off)")
    ap.add_argument("--cg", type=int, default=0, help="tours de génération de colonnes (LP + sac à dos exact) avant le MIP")
    ap.add_argument("--cg-lp-time", type=float, default=600.0)
    ap.add_argument("--cg-alpha", type=float, default=0.0, help="lissage des duaux (0 = aucun, 0,7 conseillé)")
    ap.add_argument("--cg-split", type=int, default=1, help="sous-fenêtres par besoin (colonnes diversifiées)")
    ap.add_argument("--cg-max-cols", type=int, default=0, help="colonnes ajoutées max par tour (0 = toutes)")
    ap.add_argument("--cg-min-gain", type=float, default=1e-6, help="coût réduit minimal d'une colonne ajoutée")
    ap.add_argument("--kbest", type=int, default=0, help="besoins compatibles gardés par paquet (0 = tous)")
    a = ap.parse_args()
    inst = Instance(a.instance)
    start = a.start or os.path.join(ROOT, "best", f"instance_{a.instance}.json")
    sol = json.load(open(start))
    lp = None
    lpf = os.path.join(ROOT, "runs", f"lp_{a.instance}.json")
    if os.path.exists(lpf):
        lp = json.load(open(lpf))
    extra = []
    for fn in a.extra_sols:
        try:
            with open(fn) as f:
                so = json.load(f)
        except Exception as e:
            print(f"  extra {fn} ignoré : {e!r}", flush=True)
            continue
        pk2 = {}
        for d, m in so["dataMappings"]:
            pk2.setdefault((m, inst.ds[d][0]), []).append(d)
        extra.extend(pk2.values())
    if a.gen:
        import random
        gen = generate_packages(inst, sol, a.gen, a.delta, random.Random(a.seed))
        print(f"  {len(gen)} paquets échantillonnés (gen={a.gen} delta={a.delta})", flush=True)
        extra.extend(gen)
    packs = packages_from_solution(inst, sol, singletons=not a.no_singletons, subsets=a.subsets, extra=extra)
    keep = {}
    pk = {}
    for d, m in sol["dataMappings"]:
        pk.setdefault((m, inst.ds[d][0]), []).append(d)
    for (m, t), ds in pk.items():
        keep.setdefault(tuple(sorted(ds)), set()).add(m)
    M, G = candidate_models(inst, lp, a.theta)
    # les modèles de la solution de départ sont toujours candidats (la solution courante reste admissible)
    src = {s for s, _ in sol["modelMappings"]}
    for d, m in sol["dataMappings"]:
        (G if m in src else M).add(m)
    for _, m in sol["modelMappings"]:
        M.add(m)
    print(f"inst {a.instance} départ {start} : {len(packs)} paquets, {len(M)} modèles candidats, {len(G)} générateurs candidats (theta={a.theta} kbest={a.kbest} subsets={a.subsets})", flush=True)
    # hint : rôles et affectations de la solution de départ
    gens_on = {s for s, _ in sol["modelMappings"]}
    cov = {(t, inst.reqs[s][0][0]) for s, t in sol["modelMappings"]}
    trained = (set(pk_m for pk_m, _ in pk) | {t for _, t in sol["modelMappings"]}) - gens_on
    defiled = {m: (any(inst.ds[d][2] for (mm, t), ds in pk.items() if mm == m for d in ds)
                   or any((m, t) in cov for t in range(4))) for m in trained}
    cur = {(tuple(sorted(ds)), m, 1 if m in gens_on else 0): True for (m, t), ds in pk.items()}
    newsol, roles, val, bound = build_and_solve(inst, packs, M, G, a.time, gap=a.gap, kbest=a.kbest,
                                                rc=reduced_costs(inst, lp), keep=keep,
                                                hint=(trained, defiled, cov, gens_on, cur), lex_time=a.lex,
                                                cg_rounds=a.cg, cg_lp_time=a.cg_lp_time, cg_alpha=a.cg_alpha, cg_split=a.cg_split,
                                                cg_max_cols=a.cg_max_cols, cg_min_gain=a.cg_min_gain)
    out = a.out or os.path.join(ROOT, "runs", f"rematch_{a.instance}.json")
    txt = json.dumps(newsol, separators=(",", ":"))
    with open(out, "w") as f:
        f.write(txt)
    with open(out.replace(".json", "_roles.json"), "w") as f:
        json.dump(roles, f)
    from save_if_better import evaluate, save_if_better
    sc, ok, msg = evaluate(a.instance, txt, inst.txt)
    print(f"  score officiel {sc} valide={ok} {msg} ; MIP {val:.0f} (borne {bound})", flush=True)
    if a.save and ok:
        save_if_better(a.instance, txt, method=f"rematch theta={a.theta} time={a.time:.0f}{' lex' if a.lex else ''}{' cg%d' % a.cg if a.cg else ''}", dataset_txt=inst.txt)


if __name__ == "__main__":
    main()
