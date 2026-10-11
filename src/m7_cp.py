#!/usr/bin/env python3
"""m7 — Maître entier (set-partitioning de colonnes exactes + rôles) résolu par CP-SAT, hint = best.
Les colonnes viennent de m7_cg.py (--out X : fichier X.cols.json). Même modèle que le MIP HiGHS de m7_cg.py.
Usage : python src/m7_cp.py 2 --cols runs/m7_pool_2_a.json.cols.json [--time 1200] [--workers 12] [--save]
"""
import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np
from ortools.sat.python import cp_model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402
from save_if_better import evaluate  # noqa: E402
from m7_cg import Master, packets_of_solution, realize, log  # noqa: E402


class CB(cp_model.CpSolverSolutionCallback):
    def __init__(self, k, inst, M, vars_, a, t0):
        super().__init__()
        self.k, self.inst, self.M, self.v, self.a, self.t0 = k, inst, M, vars_, a, t0
        self.best = 0

    def on_solution_callback(self):
        obj = int(self.ObjectiveValue())
        log(f"  CP-SAT solution maître {obj} (borne {self.BestObjectiveBound():.0f}) à {time.time()-self.t0:.0f}s")
        if obj <= self.best:
            return
        self.best = obj
        M = self.M
        x = np.zeros(len(M.cost))
        for j, var in self.v.items():
            if self.Value(var):
                x[j] = 1
        sol, dropped = realize(self.inst, M, x)
        txt = json.dumps(sol)
        val, ok, msg = evaluate(self.k, txt)
        log(f"  réalisation : {val} valide={ok} {msg} abandonnés={len(dropped)}")
        if ok and self.a.out:
            with open(self.a.out, "w") as f:
                f.write(txt)
            if self.a.save:
                subprocess.run([sys.executable, os.path.join(ROOT, "src", "save_if_better.py"), str(self.k), self.a.out,
                                "--method", f"m7 CP-SAT set-partitioning cols={os.path.basename(self.a.cols[0])}"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("--cols", nargs="+", required=True)
    ap.add_argument("--start", default=None)
    ap.add_argument("--time", type=float, default=1200)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--out", default=None)
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--escale", type=int, default=1000, help="diviseur de l'énergie (arrondi conservateur)")
    a = ap.parse_args()
    k = a.instance
    inst = Instance(k)
    t0 = time.time()
    sol0 = json.load(open(a.start or os.path.join(ROOT, "best", f"instance_{k}.json")))
    roles0, pk0 = packets_of_solution(inst, sol0)
    P0 = json.load(open(a.cols[0]))
    cand = set(P0["cand"]) if P0["cand"] else None
    M = Master(inst, cand=cand)
    assert [tuple(x) for x in P0["slots"]] == [tuple(x) for x in M.slots]
    for (m, t), ids in pk0.items():
        kk = [j for j, (mm_, tt, lb, u) in enumerate(M.slots) if mm_ == m and tt == t][0]
        M.add_column(kk, ids)
    for fn in a.cols:
        P = json.load(open(fn))
        n = sum(M.add_column(kk, ids) for kk, ids, s in P["cols"])
        log(f"chargé {fn}: +{n} colonnes ({len(M.cols)})")
    nm = M.nm
    mdl = cp_model.CpModel()
    V = {}
    for m in range(nm):
        if m in M.fi: V[M.fi[m]] = mdl.NewBoolVar(f"f{m}")
        V[M.hi[m]] = mdl.NewBoolVar(f"h{m}")
        if m in M.yi: V[M.yi[m]] = mdl.NewBoolVar(f"y{m}")
        for t, lb, u in inst.reqs[m]:
            V[M.zi[(m, t)]] = mdl.NewBoolVar(f"z{m}_{t}")
    lam = {}
    for j in range(len(M.cols)):
        lam[j] = mdl.NewBoolVar(f"l{j}")
        V[M.nrole + j] = lam[j]
    # datasets : au plus une colonne
    byd = {}
    byslot = {}
    for j, (kk, ids, size) in enumerate(M.cols):
        byslot.setdefault(kk, []).append(j)
        for d in ids:
            byd.setdefault(d, []).append(j)
    for d, js in byd.items():
        mdl.AddAtMostOne(lam[j] for j in js)
    for kk, (m, t, lb, u) in enumerate(M.slots):
        js = byslot.get(kk, [])
        if js:
            mdl.Add(sum(lam[j] for j in js) == V[M.fi[m]])
        else:
            mdl.Add(V[M.fi[m]] == 0)
    # énergie (échelle conservatrice)
    es = a.escale
    cap = inst.cap // es
    terms = []
    for m in range(nm):
        e = -(-inst.energy[m] // es)
        for key in (M.fi.get(m), M.hi[m], M.yi.get(m)):
            if key is not None:
                terms.append(e * V[key])
    mdl.Add(sum(terms) <= cap)
    # données totales par type ; générateurs par type
    for t in range(4):
        tt = []
        gz, gy = [], []
        for m in range(nm):
            for t2, lb, u in inst.reqs[m]:
                if t2 == t:
                    tt.append(lb * V[M.hi[m]]); tt.append(-lb * V[M.zi[(m, t)]]); gz.append(V[M.zi[(m, t)]])
            if m in M.yi and inst.reqs[m][0][0] == t:
                tt.append(inst.reqs[m][0][1] * V[M.yi[m]]); gy.append(V[M.yi[m]])
        for j, (kk, ids, size) in enumerate(M.cols):
            if M.slots[kk][1] == t:
                tt.append(size * lam[j])
        mdl.Add(sum(tt) <= M.T[t])
        mdl.Add(sum(gz) <= sum(gy))
    for m in range(nm):
        gub = [V[M.hi[m]]] + ([V[M.fi[m]]] if m in M.fi else []) + ([V[M.yi[m]]] if m in M.yi else [])
        mdl.AddAtMostOne(gub)
        for t, lb, u in inst.reqs[m]:
            mdl.AddImplication(V[M.zi[(m, t)]], V[M.hi[m]])
            if lb > u:
                mdl.AddImplication(V[M.hi[m]], V[M.zi[(m, t)]])
    mdl.Maximize(sum(inst.value[m] * V[M.fi[m]] for m in M.fi) + sum((inst.value[m] // 2) * V[M.hi[m]] for m in range(nm)))
    # hint
    x0 = {}
    for m in roles0["f"]: x0[M.fi[m]] = 1
    for m in roles0["h"]:
        x0[M.hi[m]] = 1
        for t in roles0["z"].get(m, []): x0[M.zi[(m, t)]] = 1
    for m in roles0["y"]: x0[M.yi[m]] = 1
    for j, (kk, ids, s) in enumerate(M.cols):
        m, t, lb, u = M.slots[kk]
        if (m, t) in pk0 and tuple(sorted(pk0[(m, t)])) == ids:
            x0[M.nrole + j] = 1
    for key, var in V.items():
        mdl.AddHint(var, x0.get(key, 0))
    log(f"CP-SAT : {len(V)} booléens ({len(M.cols)} colonnes), limite {a.time}s, {a.workers} workers")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = a.time
    solver.parameters.num_workers = a.workers
    solver.parameters.log_search_progress = True
    solver.parameters.log_to_stdout = False
    solver.log_callback = lambda s: open(os.path.join(ROOT, "logs", f"m7_cpsat_{k}.log"), "a").write(s + "\n")
    cb = CB(k, inst, M, V, a, t0)
    st = solver.Solve(mdl, cb)
    log(f"fin : {solver.StatusName(st)} obj {solver.ObjectiveValue():.0f} borne {solver.BestObjectiveBound():.0f} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
