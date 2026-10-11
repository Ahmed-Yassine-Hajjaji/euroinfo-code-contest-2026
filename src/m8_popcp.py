#!/usr/bin/env python3
"""m8 : même set-partitioning par type que m8_popmip (colonnes = paquets observés dans une population), résolu par
CP-SAT (hint = solution courante). Option --target N : contrainte « consommation <= courante - N » (faisabilité ciblée,
pour libérer N unités du type en datasets entiers). Puis m8_apply.
Usage : python src/m8_popcp.py <k> --start S --pool fichiers... --types T [--time 600] [--workers 4] [--target 0] [--out f] [--save]
"""
import argparse, glob, json, os, sys, time
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from greedy import Instance
from m3_prep import slots_of
from save_if_better import evaluate, save_if_better
from m8_popmip import packs_by_slot
import m8_apply

TN = "ntic"

def solve_type(inst, slots, assign, pool_packs, T, tlimit, workers, target, seed):
    from ortools.sat.python import cp_model
    sidx = [i for i, s in enumerate(slots) if s[0] == T]
    cur = defaultdict(set)
    for d, a in enumerate(assign):
        if a >= 0:
            cur[a].add(d)
    cols = []; seen = set()
    for i in sidx:
        t, lb, ub, fo, m = slots[i]
        p = frozenset(cur[i]); cols.append((i, p)); seen.add((i, p))
        for pk in pool_packs.get((m, T), ()):
            if (i, pk) in seen:
                continue
            s = sum(inst.ds[d][1] for d in pk)
            if not (lb <= s <= ub) or (fo and any(inst.ds[d][2] for d in pk)):
                continue
            seen.add((i, pk)); cols.append((i, pk))
    mdl = cp_model.CpModel()
    x = [mdl.NewBoolVar(f"x{j}") for j in range(len(cols))]
    by_slot = defaultdict(list); by_ds = defaultdict(list)
    for j, (i, p) in enumerate(cols):
        by_slot[i].append(j)
        for d in p:
            by_ds[d].append(j)
    for i, js in by_slot.items():
        mdl.AddExactlyOne([x[j] for j in js])
    for d, js in by_ds.items():
        if len(js) > 1:
            mdl.AddAtMostOne([x[j] for j in js])
    cost = [sum(inst.ds[d][1] for d in p) for _, p in cols]
    cur_cost = sum(cost[j] for j, (i, p) in enumerate(cols) if p == frozenset(cur[i]))
    expr = sum(cost[j] * x[j] for j in range(len(cols)))
    if target > 0:
        mdl.Add(expr <= cur_cost - target)
    mdl.Minimize(expr)
    for j, (i, p) in enumerate(cols):
        mdl.AddHint(x[j], 1 if p == frozenset(cur[i]) else 0)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tlimit
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = seed
    t0 = time.time()
    st = solver.Solve(mdl)
    name = solver.StatusName(st)
    val = solver.ObjectiveValue() if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None
    print(f"type {TN[T]}: {len(sidx)} créneaux, {len(cols)} colonnes ; conso {cur_cost} -> {val} (borne {solver.BestObjectiveBound():.0f}) {name} {time.time()-t0:.0f}s", flush=True)
    new_assign = list(assign)
    if val is None:
        return new_assign
    for d in by_ds:
        if new_assign[d] >= 0 and slots[new_assign[d]][0] == T:
            new_assign[d] = -1
    for j, (i, p) in enumerate(cols):
        if solver.Value(x[j]):
            for d in p:
                new_assign[d] = i
    return new_assign

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("k", type=int); ap.add_argument("--start", required=True); ap.add_argument("--pool", nargs="+", required=True)
    ap.add_argument("--types", type=int, nargs="*", default=[0, 1, 2, 3]); ap.add_argument("--time", type=float, default=600)
    ap.add_argument("--workers", type=int, default=4); ap.add_argument("--target", type=int, default=0); ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None); ap.add_argument("--save", action="store_true"); ap.add_argument("--method", default="m8 popcp")
    a = ap.parse_args()
    k = a.k; inst = Instance(k)
    sol = json.load(open(a.start))
    slots, assign = slots_of(inst, sol)
    pool_packs = defaultdict(set); nsol = 0
    for f in [f for pat in a.pool for f in glob.glob(pat)]:
        try:
            s = json.load(open(f)); pb = packs_by_slot(inst, s)
        except Exception:
            continue
        nsol += 1
        for key, (pk, full) in pb.items():
            pool_packs[key].add(pk)
    print(f"{nsol} solutions, {sum(len(v) for v in pool_packs.values())} paquets distincts", flush=True)
    for T in a.types:
        assign = solve_type(inst, slots, assign, pool_packs, T, a.time, a.workers, a.target, a.seed)
    dm = [[d, slots[s][4]] for d, s in enumerate(assign) if s >= 0]
    new = {"dataMappings": dm, "modelMappings": sol["modelMappings"]}
    txt = json.dumps(new); sc, ok, msg = evaluate(k, txt, inst.txt); s0 = evaluate(k, json.dumps(sol), inst.txt)[0]
    free = sorted((TN[inst.ds[d][0]], inst.ds[d][1], 'C' if inst.ds[d][2] else 'L') for d, s in enumerate(assign) if s < 0)
    waste = sum(inst.ds[d][1] for d, s in enumerate(assign) if s >= 0) - sum(lb for _, lb, _, _, _ in slots)
    print(f"m8_popcp : {s0} -> {sc} valide={ok} {msg if not ok else ''} gaspillage {waste} libres={free}", flush=True)
    out = a.out or os.path.join("runs", "m8_popcp.json")
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
