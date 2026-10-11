#!/usr/bin/env python3
"""m8 : ré-empaquetage exact PAR TYPE à rôles fixés (ceux de --start), colonnes = paquets observés dans une population
de solutions (même modèle, même créneau) + paquet courant. Set-partitioning HiGHS : chaque créneau exactement un paquet,
chaque dataset au plus un ; objectif = min consommation (libère des datasets ENTIERS), optionnellement avec un bonus
sur les datasets libres libérés (pour les bascules). Puis m8_apply (bascules hc -> f) et sauvegarde.
Usage : python src/m8_popmip.py <k> --start best/instance_6.json --pool runs/m8/pop/*.json [--types 3] [--time 300]
        [--out runs/m8_popmip.json] [--save]
"""
import argparse, glob, json, os, sys, time
from collections import defaultdict
import numpy as np
from scipy.sparse import coo_matrix
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from greedy import Instance
from m3_prep import slots_of
from save_if_better import evaluate, save_if_better
from fin_mip4 import make
import m8_apply

TN = "ntic"

def packs_by_slot(inst, sol):
    """{(modèle, type): (frozenset datasets, free_only)} pour les créneaux remplis par des datasets."""
    src = {s for s, _ in sol["modelMappings"]}
    cov = {(t, inst.reqs[s][0][0]) for s, t in sol["modelMappings"]}
    byd = defaultdict(list)
    for d, m in sol["dataMappings"]:
        byd[m].append(d)
    out = {}
    for m, ds in byd.items():
        full = m not in src and not any(inst.ds[d][2] for d in ds) and not any((m, t) in cov for t in range(4))
        for t in {inst.ds[d][0] for d in ds}:
            if (m, t) in cov:
                continue
            out[(m, t)] = (frozenset(d for d in ds if inst.ds[d][0] == t), full)
    return out

def solve_type(inst, slots, assign, pool_packs, T, tlimit, threads, bonus_free):
    sidx = [i for i, s in enumerate(slots) if s[0] == T]
    cur = defaultdict(set)
    for d, a in enumerate(assign):
        if a >= 0:
            cur[a].add(d)
    cols = []  # (slot i, frozenset)
    seen = set()
    for i in sidx:
        t, lb, ub, fo, m = slots[i]
        p = frozenset(cur[i])
        cols.append((i, p)); seen.add((i, p))
        for pk in pool_packs.get((m, T), ()):
            if (i, pk) in seen:
                continue
            s = sum(inst.ds[d][1] for d in pk)
            if not (lb <= s <= ub) or (fo and any(inst.ds[d][2] for d in pk)):
                continue
            seen.add((i, pk)); cols.append((i, pk))
    n = len(cols)
    dl = sorted({d for _, p in cols for d in p})
    dmap = {d: j for j, d in enumerate(dl)}
    rows, cs, vals = [], [], []
    ns = len(sidx); smap = {i: j for j, i in enumerate(sidx)}
    for j, (i, p) in enumerate(cols):
        rows.append(smap[i]); cs.append(j); vals.append(1.0)
        for d in p:
            rows.append(ns + dmap[d]); cs.append(j); vals.append(1.0)
    A = coo_matrix((vals, (rows, cs)), shape=(ns + len(dl), n)).tocsc()
    # lignes créneaux : = 1 (on met lower = upper via deux contraintes : A x <= 1 et -A x <= -1)
    from scipy.sparse import vstack
    A2 = vstack([A, -A[:ns]]).tocsc()
    rhs = np.concatenate([np.ones(ns), np.ones(len(dl)), -np.ones(ns)])
    obj = np.array([sum(inst.ds[d][1] * (1.0 + (bonus_free if not inst.ds[d][2] else 0.0)) for d in p) for _, p in cols])
    h = make(obj, np.zeros(n), np.ones(n), A2, rhs, True, threads)
    h.setOptionValue("time_limit", tlimit); h.setOptionValue("mip_rel_gap", 0.0)
    import highspy
    x0 = np.zeros(n)
    for j, (i, p) in enumerate(cols):
        if p == frozenset(cur[i]):
            x0[j] = 1.0
    s0 = highspy.HighsSolution(); s0.col_value = list(x0); h.setSolution(s0)
    t0 = time.time(); h.run()
    x = np.round(np.array(h.getSolution().col_value))
    info = h.getInfo()
    print(f"type {TN[T]}: {ns} créneaux, {len(dl)} datasets, {n} colonnes ({n/ns:.1f}/créneau) ; conso {obj @ x0:.0f} -> {obj @ x:.0f} "
          f"(borne {info.mip_dual_bound:.0f}) {h.modelStatusToString(h.getModelStatus())} {time.time()-t0:.0f}s", flush=True)
    new_assign = list(assign)
    for d in dl:
        if inst.ds[d][0] == T and new_assign[d] >= 0 and slots[new_assign[d]][0] == T:
            new_assign[d] = -1
    for j, (i, p) in enumerate(cols):
        if x[j] > .5:
            for d in p:
                new_assign[d] = i
    return new_assign

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("k", type=int); ap.add_argument("--start", required=True); ap.add_argument("--pool", nargs="+", required=True)
    ap.add_argument("--types", type=int, nargs="*", default=[0, 1, 2, 3]); ap.add_argument("--time", type=float, default=300)
    ap.add_argument("--threads", type=int, default=1); ap.add_argument("--out", default=None); ap.add_argument("--save", action="store_true")
    ap.add_argument("--bonus-free", type=float, default=0.0, help="poids supplémentaire des datasets libres dans la consommation")
    ap.add_argument("--method", default="m8 popmip")
    a = ap.parse_args()
    k = a.k; inst = Instance(k)
    sol = json.load(open(a.start))
    slots, assign = slots_of(inst, sol)
    pool_packs = defaultdict(set)
    files = [f for pat in a.pool for f in glob.glob(pat)]
    nsol = 0
    for f in files:
        try:
            s = json.load(open(f))
            if "modelMappings" not in s:
                continue
        except Exception:
            continue
        try:
            pb = packs_by_slot(inst, s)
        except Exception:
            continue  # solution d'une autre instance
        nsol += 1
        for key, (pk, full) in pb.items():
            pool_packs[key].add(pk)
    print(f"{nsol} solutions, {sum(len(v) for v in pool_packs.values())} paquets distincts sur {len(pool_packs)} créneaux", flush=True)
    for T in a.types:
        assign = solve_type(inst, slots, assign, pool_packs, T, a.time, a.threads, a.bonus_free)
    dm = [[d, slots[s][4]] for d, s in enumerate(assign) if s >= 0]
    new = {"dataMappings": dm, "modelMappings": sol["modelMappings"]}
    txt = json.dumps(new)
    sc, ok, msg = evaluate(k, txt, inst.txt)
    s0 = evaluate(k, json.dumps(sol), inst.txt)[0]
    free = sorted((TN[inst.ds[d][0]], inst.ds[d][1], 'C' if inst.ds[d][2] else 'L') for d, s in enumerate(assign) if s < 0)
    waste = sum(inst.ds[d][1] for d, s in enumerate(assign) if s >= 0) - sum(lb for _, lb, _, _, _ in slots)
    print(f"m8_popmip : {s0} -> {sc} valide={ok} {msg if not ok else ''} gaspillage {waste} libres={free}", flush=True)
    out = a.out or os.path.join("runs", "m8_popmip.json")
    if ok:
        open(out, "w").write(txt)
        new2, gain, desc = m8_apply.search(inst, new, quiet=True)
        if gain > 0:
            txt2 = json.dumps(new2); sc2, ok2, _ = evaluate(k, txt2, inst.txt)
            print(f"  bascule : {sc} -> {sc2} valide={ok2} : {desc}", flush=True)
            if ok2 and sc2 > sc:
                open(out.replace(".json", "_bas.json"), "w").write(txt2)
                if a.save:
                    save_if_better(k, txt2, method=f"{a.method} + {desc[:60]}", dataset_txt=inst.txt)

if __name__ == "__main__":
    main()
