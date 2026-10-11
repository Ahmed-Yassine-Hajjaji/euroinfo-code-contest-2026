#!/usr/bin/env python3
"""m6 : croisement de deux solutions A (meilleure) et B.

1. Partie commune figée : modèles entraînés dont la description (paquets par type + types couverts par générateur) est
   identique dans A et B, et générateurs dont le paquet est identique (équilibrés par type avec les créneaux couverts figés).
2. Le reste est reconstruit par un MIP HiGHS « paquets <-> besoins » (copie adaptée de src/rematch.py) : colonnes = paquets
   restants de A (chacun omis avec probabilité --drop) + paquets restants de B (bonus --bonus par paquet, départage des
   ex æquo vers B) + sous-ensembles (--subsets) + datasets seuls (--singletons) ; modèles candidats par coût réduit (--theta).
   Énergie = cap - énergie figée. Hint = reste de A.
3. Enfant = partie figée + sortie du MIP, validé par le scoreur officiel.

Usage : python src/m6_cross.py <k> <A.json> <B.json> <out.json> [--time 120] [--theta 40] [--kbest 30] [--bonus 1e-4]
        [--drop 0.0] [--seed 0] [--subsets] [--no-singletons] [--lex 0]
Sortie (dernière ligne) : "m6_cross score=S valide=V kept=K/NS dA=.. dB=.. waste=W"
"""
import argparse
import json
import os
import random
import sys
import time

import numpy as np
from scipy.sparse import coo_matrix

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m6_common import ROOT, Instance, packs_of, pack_set, distance, waste_of  # noqa: E402
from rematch import candidate_models, reduced_costs  # noqa: E402
from save_if_better import evaluate  # noqa: E402


def describe(inst, sol):
    """Description des modèles entraînés et des générateurs : desc[m] = (frozenset{(t, ds)}, frozenset{types couverts}),
    gens = {s: (cible, ds)}."""
    pk = packs_of(inst, sol)
    src = {s: t for s, t in sol["modelMappings"]}
    covered = {}
    for s, t in sol["modelMappings"]:
        covered.setdefault(t, set()).add(inst.reqs[s][0][0])
    trained = ({m for m, _ in pk} | set(src.values())) - set(src)
    desc = {}
    for m in trained:
        desc[m] = (frozenset((t, ds) for (mm, t), ds in pk.items() if mm == m), frozenset(covered.get(m, ())))
    gens = {s: pk.get((s, inst.reqs[s][0][0]), ()) for s in src}
    return desc, gens, pk


def split_common(inst, A, B):
    """Retourne (kept_models, kept_gens, kept_dm, kept_mm) : partie commune figée et équilibrée par type."""
    dA, gA, _ = describe(inst, A)
    dB, gB, _ = describe(inst, B)
    kept = {m for m in dA if m in dB and dA[m] == dB[m]}
    kgens = {s for s in gA if s in gB and gA[s] == gB[s] and len(gA[s]) > 0}
    # équilibre par type : autant de générateurs figés que de créneaux couverts figés
    while True:
        changed = False
        for t in range(4):
            gl = sorted(s for s in kgens if inst.reqs[s][0][0] == t)
            tl = sorted((m, t) for m in kept for tt in dA[m][1] if tt == t)
            n = min(len(gl), len(tl))
            for s in gl[n:]:
                kgens.discard(s); changed = True
            for m, _ in tl[n:]:
                kept.discard(m); changed = True
        if not changed:
            break
    kept_dm, kept_mm = [], []
    for m in kept:
        for t, ds in dA[m][0]:
            kept_dm.extend([d, m] for d in ds)
    for t in range(4):
        gl = sorted(s for s in kgens if inst.reqs[s][0][0] == t)
        tl = sorted(m for m in kept for tt in dA[m][1] if tt == t)
        assert len(gl) == len(tl)
        for s, m in zip(gl, tl):
            kept_mm.append([s, m])
            kept_dm.extend([d, s] for d in gA[s])
    return kept, kgens, kept_dm, kept_mm


def subset_min_sum(items, lb, ub):
    """Sous-ensemble de items [(d, size)] de somme minimale dans [lb, ub] (DP bitset), ou None."""
    if ub < lb or not items:
        return None
    mask = (1 << (ub + 1)) - 1
    reach = 1
    snaps = []
    for d, s in items:
        snaps.append(reach)
        reach |= (reach << s) & mask
    hi = reach >> lb
    if hi == 0:
        return None
    best = lb + ((hi & -hi).bit_length() - 1)
    out, cur = [], best
    for i in range(len(items) - 1, -1, -1):
        if not (snaps[i] >> cur) & 1:
            out.append(items[i][0]); cur -= items[i][1]
    assert cur == 0
    return out


def mix(inst, A, B, kept, kgens, kept_ds, p, rng, maxpool=300, maxchain=4, maxdw=10**9):
    """Enfant = rôles de A (score identique), empaquetage mélangé : pour chaque créneau X (ordre aléatoire, prob. p) on
    importe le paquet de B ; les créneaux de A qui perdent des datasets (chaîne, <= maxchain) reprennent leur paquet de B
    si possible, sinon un sous-ensemble exact (subset-sum, somme minimale dans [lb, ub]) du pool libéré. Chaîne annulée si
    un créneau ne peut pas être rempli ou si le gaspillage augmente de plus de maxdw. Tarif préservé (plein tarif : datasets
    libres seulement). Retourne fill {(m, t): ds}, trained, gens, covered, compteurs."""
    pkA, pkB = packs_of(inst, A), packs_of(inst, B)
    srcA = {s for s, _ in A["modelMappings"]}
    covA = {(t, inst.reqs[s][0][0]) for s, t in A["modelMappings"]}
    fill = {k_: v for k_, v in pkA.items() if k_[0] not in kept and k_[0] not in kgens}
    slot_of = {}
    for k_, ds in fill.items():
        for d in ds:
            slot_of[d] = k_
    free = {d for d in range(len(inst.ds)) if d not in slot_of and d not in kept_ds}
    full = {}
    for m in {m for m, _ in pkA}:
        full[m] = m not in srcA and not any(inst.ds[d][2] for (mm, t), ds in pkA.items() if mm == m for d in ds) and not any((m, t) in covA for t in range(4))

    def window(k_):
        m, t = k_
        if m in srcA:
            return inst.reqs[m][0][1:]
        return next((lb, ub) for tt, lb, ub in inst.reqs[m] if tt == t)

    def ok(k_, ds):
        lb, ub = window(k_)
        s = sum(inst.ds[d][1] for d in ds)
        return lb <= s <= ub and (not full[k_[0]] or not any(inst.ds[d][2] for d in ds))

    st = dict(tried=0, chains=0, imported=0, failed=0, dw=0)
    order = [k_ for k_ in fill if k_ in pkB and pkB[k_] != fill[k_]]
    rng.shuffle(order)
    for X in order:
        if rng.random() >= p or fill.get(X) == pkB[X]:
            continue
        pb = pkB[X]
        st["tried"] += 1
        if not ok(X, pb) or any(d in free for d in pb):  # on ne touche jamais aux datasets libres de A
            st["failed"] += 1; continue
        Y = {slot_of[d] for d in pb if d in slot_of and slot_of[d] != X}
        if len(Y) > maxchain:
            st["failed"] += 1; continue
        saved = {X: fill[X]}
        saved.update({y: fill[y] for y in Y})
        pool = set()
        for ds in saved.values():
            pool.update(ds)
        pool.difference_update(pb)
        new = {X: pb}
        good = True
        for y in rng.sample(sorted(Y), len(Y)):
            pby = pkB.get(y)
            if pby is not None and set(pby) <= pool and ok(y, pby):
                new[y] = pby; pool.difference_update(pby); continue
            lb, ub = window(y)
            t = y[1]
            cand = [(d, inst.ds[d][1]) for d in pool if inst.ds[d][0] == t and (not full[y[0]] or not inst.ds[d][2]) and inst.ds[d][1] <= ub]
            if len(cand) > maxpool:
                cand = rng.sample(cand, maxpool)
            sub = subset_min_sum(cand, lb, ub)
            if sub is None:
                good = False; break
            new[y] = tuple(sorted(sub)); pool.difference_update(sub)
        if not good:
            st["failed"] += 1; continue
        dw = sum(inst.ds[d][1] for ds in new.values() for d in ds) - sum(inst.ds[d][1] for ds in saved.values() for d in ds)
        if dw > maxdw:
            st["failed"] += 1; continue
        for s_, ds in saved.items():
            for d in ds:
                slot_of.pop(d, None); free.add(d)
        for s_, ds in new.items():
            fill[s_] = ds
            for d in ds:
                slot_of[d] = s_; free.discard(d)
        st["chains"] += 1; st["imported"] += 1 + len(Y); st["dw"] += dw
    trainedA = ({m for m, _ in pkA} | {t for _, t in A["modelMappings"]}) - srcA
    trained = trainedA - kept
    gens = srcA - kgens
    covered = {(m, t) for (m, t) in covA if m in trained}
    st["free"] = len(free)
    return fill, trained, gens, covered, st


def solve_rest(inst, lp, A, B, kept, kgens, a, log):
    rng = random.Random(a.seed)
    nm = len(inst.value)
    kept_ds = set()
    pkA, pkB = packs_of(inst, A), packs_of(inst, B)
    srcA = {s for s, _ in A["modelMappings"]}
    srcB = {s for s, _ in B["modelMappings"]}
    for (m, t), ds in pkA.items():
        if m in kept or m in kgens:
            kept_ds.update(ds)
    E_kept = sum(inst.energy[m] for m in kept | kgens)
    # paquets
    packs, seen, fromB = [], set(), set()

    def add(ds, b=False):
        key = tuple(sorted(ds))
        if key in seen or any(d in kept_ds for d in key):
            return
        seen.add(key)
        if b:
            fromB.add(len(packs))
        packs.append((inst.ds[key[0]][0], sum(inst.ds[d][1] for d in key), not any(inst.ds[d][2] for d in key), list(key)))

    from itertools import combinations
    nA = nB = 0
    for (m, t), ds in pkA.items():
        if m in kept or m in kgens:
            continue
        if a.drop > 0 and rng.random() < a.drop:
            continue
        add(ds); nA += 1
        if a.subsets and 2 <= len(ds) <= 6:
            for r in range(1, len(ds)):
                for sub in combinations(ds, r):
                    add(sub)
    for (m, t), ds in pkB.items():
        if m in kept or m in kgens:
            continue
        add(ds, b=True); nB += 1
        if a.subsets and 2 <= len(ds) <= 6:
            for r in range(1, len(ds)):
                for sub in combinations(ds, r):
                    add(sub, b=True)
    if not a.no_singletons:
        for d in range(len(inst.ds)):
            add([d])
    # modèles candidats
    M, G = candidate_models(inst, lp, a.theta) if a.theta >= 0 else (set(), set())
    for sol, src in ((A, srcA), (B, srcB)):
        for d, m in sol["dataMappings"]:
            (G if m in src else M).add(m)
        for _, m in sol["modelMappings"]:
            M.add(m)
    M -= kept | kgens
    G -= kept | kgens
    rcm, rcg = reduced_costs(inst, lp)
    # hint = enfant glouton (mélange A/B + remplissage exact)
    fill, trainedH, gensH, coveredH, st = mix(inst, A, B, kept, kgens, kept_ds, a.mix, rng, maxchain=a.maxchain, maxdw=a.maxdw)
    for ds in fill.values():
        add(ds)
    defiledH = {m: any(inst.ds[d][2] for (mm, t), ds in fill.items() if mm == m for d in ds) or any((m, t) in coveredH for t in range(4)) for m in trainedH}
    curH = {(ds, m, 1 if m in gensH else 0) for (m, t), ds in fill.items()}
    log(f"  mélange p={a.mix} : {st} ; entraînés {len(trainedH)} gén. {len(gensH)}")
    if a.time <= 0:  # pas de MIP : l'enfant est le mélange (rôles de A)
        dm = [[d, m] for (m, t), ds in fill.items() for d in ds]
        mm = []
        for t in range(4):
            gl = sorted(g for g in gensH if inst.reqs[g][0][0] == t)
            tl = sorted(m for (m, tt) in coveredH if tt == t)
            assert len(gl) >= len(tl), (t, len(gl), len(tl))
            mm.extend([g, m] for g, m in zip(gl, tl))
            for g in gl[len(tl):]:
                dm = [[d, mm_] for d, mm_ in dm if mm_ != g]
        return dm, mm
    log(f"  figé : {len(kept)} modèles, {len(kgens)} générateurs, {len(kept_ds)} datasets, énergie {E_kept/inst.cap:.4f} ; "
        f"reste : {nA} paquets A, {nB} paquets B, {len(packs)} colonnes-paquets, {len(M)} modèles, {len(G)} gén. candidats")
    # ---------------- MIP (adapté de rematch.build_and_solve) ----------------
    t0 = time.time()
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
    for m in sorted(M | G):
        rhs_lo.append(-np.inf); rhs_hi.append(1.0)
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
    RE = r; r += 1; rhs_lo.append(-np.inf); rhs_hi.append(1.0 - E_kept / inst.cap - 2e-7)
    for m in M:
        rows += [RE, RE]; cols += [fi[m], hi_[m]]; vals += [inst.energy[m] / inst.cap] * 2
    for g in G:
        rows.append(RE); cols.append(yi[g]); vals.append(inst.energy[g] / inst.cap)
    acol = []
    keep = {}
    for (m, t), ds in list(pkA.items()) + list(pkB.items()) + list(fill.items()):
        keep.setdefault(ds, set()).add(m)
    for t in range(4):
        L = np.array([x[0] for x in needs[t]]); U = np.array([x[1] for x in needs[t]]); Mn = [x[2] for x in needs[t]]
        Lg = np.array([x[0] for x in gens[t]]); Ug = np.array([x[1] for x in gens[t]]); Gg = [x[2] for x in gens[t]]
        RCn = np.array([rcm[m] for m in Mn]); RCg = np.array([rcg[g] for g in Gg])
        for pi, (tt, S, free, ds) in enumerate(packs):
            if tt != t:
                continue
            bonus = -a.bonus if pi in fromB else 0.0
            keep_p = keep.get(tuple(ds), set())
            if len(L):
                js = np.nonzero((L <= S) & (S <= U))[0]
                if a.kbest and len(js) > a.kbest:
                    js = set(js[np.argsort(-RCn[js])[:a.kbest]].tolist()) | {j for j in range(len(Mn)) if Mn[j] in keep_p and L[j] <= S <= U[j]}
                for j in js:
                    m = Mn[j]
                    c = newcol(bonus)
                    acol.append((c, pi, 0, (m, t)))
                    rows.append(R2[(m, t)]); cols.append(c); vals.append(1)
                    if not free:
                        rows.append(R3[(m, t)]); cols.append(c); vals.append(1)
                    for d in ds:
                        rows.append(RD[d]); cols.append(c); vals.append(1)
            if len(Lg):
                js = np.nonzero((Lg <= S) & (S <= Ug))[0]
                if a.kbest and len(js) > a.kbest:
                    js = set(js[np.argsort(-RCg[js])[:a.kbest]].tolist()) | {j for j in range(len(Gg)) if Gg[j] in keep_p and Lg[j] <= S <= Ug[j]}
                for j in js:
                    g = Gg[j]
                    c = newcol(bonus)
                    acol.append((c, pi, 1, g))
                    rows.append(R4[g]); cols.append(c); vals.append(1)
                    for d in ds:
                        rows.append(RD[d]); cols.append(c); vals.append(1)
    A_ = coo_matrix((np.array(vals, dtype=float), (np.array(rows), np.array(cols))), shape=(r, col)).tocsc()
    log(f"  MIP : {col} colonnes ({nrole} rôles, {len(acol)} affectations), {r} lignes, {A_.nnz} nz, construit en {time.time()-t0:.0f}s")
    import highspy
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("threads", int(os.environ.get("HIGHS_THREADS", "1")))
    h.setOptionValue("time_limit", float(a.time))
    h.setOptionValue("mip_rel_gap", 0.0)
    h.setOptionValue("random_seed", int(a.seed))
    lpm = highspy.HighsLp()
    lpm.num_col_ = col; lpm.num_row_ = r
    lpm.col_cost_ = np.array(obj, dtype=float); lpm.col_lower_ = np.array(lo); lpm.col_upper_ = np.array(hi)
    lpm.row_lower_ = np.array(rhs_lo); lpm.row_upper_ = np.array(rhs_hi)
    lpm.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    lpm.a_matrix_.start_ = A_.indptr.astype(np.int32); lpm.a_matrix_.index_ = A_.indices.astype(np.int32)
    lpm.a_matrix_.value_ = A_.data
    lpm.integrality_ = [highspy.HighsVarType.kInteger] * col
    h.passModel(lpm)
    # hint
    x0 = np.zeros(col)
    for m in M:
        if m in trainedH:
            x0[hi_[m] if defiledH[m] else fi[m]] = 1.0
            for t, _, _ in inst.reqs[m]:
                if (m, t) in coveredH:
                    x0[zi[(m, t)]] = 1.0
    for g in G:
        if g in gensH:
            x0[yi[g]] = 1.0
    nh = 0
    for c, pi, kind, key in acol:
        tgt = key[0] if kind == 0 else key
        if (tuple(packs[pi][3]), tgt, kind) in curH:
            x0[c] = 1.0; nh += 1
    Ax = A_ @ x0
    badr = np.nonzero((Ax > np.array(rhs_hi) + 1e-9) | (Ax < np.array(rhs_lo) - 1e-9))[0]
    cat = {"R2": set(R2.values()), "R3": set(R3.values()), "R4": set(R4.values()), "R5": set(R5), "RD": set(RD), "RE": {RE}}
    det = {k_: sum(1 for b in badr if b in v) for k_, v in cat.items() if any(b in v for b in badr)}
    log(f"  hint : {nh} affectations, valeur {-float(np.dot(np.array(obj), x0)):.2f}, lignes violées {len(badr)} {det}"
        + (f" RE: Ax={Ax[RE]:.9f} rhs={rhs_hi[RE]:.9f}" if RE in badr else ""))
    sol0 = highspy.HighsSolution(); sol0.col_value = list(x0); h.setSolution(sol0)
    h.run()
    info = h.getInfo()
    xs = np.array(h.getSolution().col_value)
    if len(xs) != col or info.primal_solution_status == 0:
        raise RuntimeError(f"HiGHS : pas de solution ({h.modelStatusToString(h.getModelStatus())})")
    x = np.round(xs)
    val = -float(np.dot(obj, x))
    log(f"  MIP : valeur {val:.2f} borne {-float(info.mip_dual_bound):.2f} ({time.time()-t0:.0f}s) {h.modelStatusToString(h.getModelStatus())}")
    if a.lex > 0:
        cons = np.zeros(col)
        for c, pi, kind, key in acol:
            cons[c] = packs[pi][1]
        idx = np.nonzero(np.array(obj))[0]
        h.addRow(-np.inf, -(val - 0.5), len(idx), idx.astype(np.int32), np.array(obj)[idx])
        h.changeColsCost(col, np.arange(col, dtype=np.int32), cons)
        h.setOptionValue("time_limit", float(a.lex))
        sol1 = highspy.HighsSolution(); sol1.col_value = list(x); h.setSolution(sol1)
        h.run()
        xs2 = np.array(h.getSolution().col_value)
        if len(xs2) == col and h.getInfo().primal_solution_status != 0:
            x2 = np.round(xs2)
            if -float(np.dot(obj, x2)) >= val - 1e-6:
                log(f"  lex : consommation {float(np.dot(cons, x)):.0f} -> {float(np.dot(cons, x2)):.0f}")
                x = x2
    dm, mm = [], []
    y = {g: x[yi[g]] > 0.5 for g in G}
    z = {(m, t): x[zi[(m, t)]] > 0.5 for (m, t) in zi}
    for c, pi, kind, key in acol:
        if x[c] > 0.5:
            tgt = key[0] if kind == 0 else key
            dm.extend([d, tgt] for d in packs[pi][3])
    for t in range(4):
        gl = [g for g in sorted(G) if y[g] and inst.reqs[g][0][0] == t]
        tl = [m for (m, tt) in sorted(zi) if tt == t and z[(m, tt)]]
        assert len(tl) <= len(gl), (t, len(tl), len(gl))
        for g, m in zip(gl, tl):
            mm.append([g, m])
        for g in gl[len(tl):]:
            dm = [[d, mm_] for d, mm_ in dm if mm_ != g]
    return dm, mm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("A"); ap.add_argument("B"); ap.add_argument("out")
    ap.add_argument("--time", type=float, default=0, help="durée du MIP de réparation (0 = pas de MIP)")
    ap.add_argument("--theta", type=float, default=40)
    ap.add_argument("--kbest", type=int, default=30)
    ap.add_argument("--bonus", type=float, default=0.0)
    ap.add_argument("--drop", type=float, default=0.0)
    ap.add_argument("--mix", type=float, default=0.3, help="probabilité d'essayer d'importer le paquet de B pour un créneau")
    ap.add_argument("--maxchain", type=int, default=4, help="créneaux de A déplacés max par import")
    ap.add_argument("--maxdw", type=int, default=10**9, help="hausse de gaspillage max par chaîne")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--subsets", action="store_true")
    ap.add_argument("--no-singletons", action="store_true")
    ap.add_argument("--lex", type=float, default=0.0)
    a = ap.parse_args()
    k = a.instance
    inst = Instance(k)
    lpf = os.path.join(ROOT, "runs", f"lp_{k}.json")
    lp = json.load(open(lpf)) if os.path.exists(lpf) else None
    A = json.load(open(a.A)); B = json.load(open(a.B))
    sA = evaluate(k, json.dumps(A), inst.txt)[0]; sB = evaluate(k, json.dumps(B), inst.txt)[0]
    log = lambda s: print(s, flush=True)  # noqa: E731
    kept, kgens, kept_dm, kept_mm = split_common(inst, A, B)
    dm, mm = solve_rest(inst, lp, A, B, kept, kgens, a, log)
    child = {"dataMappings": [[int(d), int(m)] for d, m in kept_dm + dm], "modelMappings": [[int(s), int(t)] for s, t in kept_mm + mm]}
    txt = json.dumps(child, separators=(",", ":"))
    sc, ok, msg = evaluate(k, txt, inst.txt)
    with open(a.out, "w") as f:
        f.write(txt)
    pA, pB, pC = pack_set(inst, A), pack_set(inst, B), pack_set(inst, child)
    nslots = len(pA)
    print(f"m6_cross score={sc} valide={ok} {'' if ok else msg} A={sA} B={sB} kept={len(kept)}/{len(kept_dm)}ds dAB={distance(pA, pB)} "
          f"dA={distance(pC, pA)} dB={distance(pC, pB)} slots={nslots} waste={waste_of(inst, child) if ok else '-'} "
          f"wA={waste_of(inst, A)} wB={waste_of(inst, B)}", flush=True)
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
