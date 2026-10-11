#!/usr/bin/env python3
"""m7 — Empaquetage exact d'un type par CP-SAT (processus séparé : highspy et ortools ne cohabitent pas).
Entrée JSON : {"slots": [[m, lb, ub, w]], "free": [[size, id]], "hint": {m: [ids]}, "time": s, "workers": n}
Sortie JSON : {"assign": {m: [ids]}, "status": str, "obj": v, "bound": b}
Usage : python src/m7_pack_cp.py in.json out.json
"""
import json
import sys
import time

from ortools.sat.python import cp_model

inp = json.load(open(sys.argv[1]))
slots = inp["slots"]; free = inp["free"]; hint = {int(k): v for k, v in inp.get("hint", {}).items()}
mdl = cp_model.CpModel()
nk, nd = len(slots), len(free)
a = [mdl.NewBoolVar(f"a{k}") for k in range(nk)]
x = {}
for j, (s, d) in enumerate(free):
    for k, (m, lb, u, w) in enumerate(slots):
        if s <= u:
            x[(j, k)] = mdl.NewBoolVar(f"x{j}_{k}")
for j in range(nd):
    vs = [x[(j, k)] for k in range(nk) if (j, k) in x]
    if vs:
        mdl.AddAtMostOne(vs)
for k, (m, lb, u, w) in enumerate(slots):
    tot = sum(free[j][0] * x[(j, k)] for j in range(nd) if (j, k) in x)
    mdl.Add(tot >= lb * a[k]); mdl.Add(tot <= u * a[k])
    for j in range(nd):
        if (j, k) in x:
            mdl.AddImplication(x[(j, k)], a[k])
# objectif : poids des créneaux actifs (x1000) - taille utilisée (gaspillage min) : lexicographique approx.
W = 10 ** 6
mdl.Maximize(sum(int(round(w * W)) * a[k] for k, (m, lb, u, w) in enumerate(slots))
             - sum(free[j][0] * x[(j, k)] for (j, k) in x))
pos = {d: j for j, (s, d) in enumerate(free)}
kof = {m: k for k, (m, lb, u, w) in enumerate(slots)}
hinted = set()
for m, ids in hint.items():
    if m in kof:
        k = kof[m]; mdl.AddHint(a[k], 1); hinted.add(k)
        for d in ids:
            if (pos[d], k) in x:
                mdl.AddHint(x[(pos[d], k)], 1)
for k in range(nk):
    if k not in hinted:
        mdl.AddHint(a[k], 0)
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = float(inp.get("time", 300))
solver.parameters.num_workers = int(inp.get("workers", 6))
t0 = time.time()
st = solver.Solve(mdl)
out = {"status": solver.StatusName(st), "assign": {}}
if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    out["obj"] = solver.ObjectiveValue(); out["bound"] = solver.BestObjectiveBound()
    for k, (m, lb, u, w) in enumerate(slots):
        if solver.Value(a[k]):
            out["assign"][m] = [free[j][1] for j in range(nd) if (j, k) in x and solver.Value(x[(j, k)])]
out["time"] = time.time() - t0
json.dump(out, open(sys.argv[2], "w"))
