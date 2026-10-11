#!/usr/bin/env python3
"""CP-SAT sur le cœur du sac à dos des rôles (instance sans générateurs, ex. 4), coefficients entiers exacts.

Fixation par coût réduit LP (cf. fin_mip4.py) puis CP-SAT avec hint = best/.
Usage : python src/fin_cp4.py <k> [--time 600] [--target T] [--workers 2] [--out runs/fin_roles_k_cp.json]
"""
import argparse
import json
import os
import sys
import time

import numpy as np
from ortools.sat.python import cp_model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402
from fin_mip4 import build, hint_from_best  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("--time", type=float, default=600)
    ap.add_argument("--target", type=float, default=None)
    ap.add_argument("--fix-target", type=float, default=None, help="cible utilisée pour la fixation (défaut = target)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    k = a.instance
    inst = Instance(k)
    nm = len(inst.value)
    obj, ub, A, rhs = build(inst)
    x0 = hint_from_best(inst, k)
    v0 = int(round(-obj @ x0))
    target = a.target if a.target is not None else v0 + 1
    ft = a.fix_target if a.fix_target is not None else target
    from scipy.optimize import linprog  # HiGHS embarqué dans scipy (highspy et ortools sont incompatibles)
    res = linprog(obj, A_ub=A.tocsr(), b_ub=rhs, bounds=list(zip([0.0] * len(obj), ub)), method="highs")
    xl = res.x; rc = res.lower.marginals + res.upper.marginals
    bound = -res.fun
    gapv = bound - ft
    lo_, hi_ = np.zeros(len(obj), dtype=int), ub.astype(int).copy()
    for j in range(len(obj)):
        if hi_[j] == 0:
            continue
        if xl[j] < 1e-9 and rc[j] > gapv + 1e-6:
            hi_[j] = 0
        elif xl[j] > 1 - 1e-9 and -rc[j] > gapv + 1e-6:
            lo_[j] = 1
    print(f"inst {k}: hint {v0}, borne LP {bound:.2f}, fixation à {ft:.0f}, libres {int((hi_ > lo_).sum())}", flush=True)

    F = [0] * 4
    T = [0] * 4
    for t, sz, c in inst.ds:
        T[t] += sz
        if not c:
            F[t] += sz
    M = cp_model.CpModel()
    x = [M.NewIntVar(int(lo_[j]), int(hi_[j]), f"x{j}") for j in range(2 * nm)]
    for m in range(nm):
        M.Add(x[2 * m] + x[2 * m + 1] <= 1)
    M.Add(sum(inst.energy[m] * (x[2 * m] + x[2 * m + 1]) for m in range(nm)) <= inst.cap)
    for t in range(4):
        fl = [(lb, m) for m in range(nm) for tt, lb, _ in inst.reqs[m] if tt == t]
        M.Add(sum(lb * x[2 * m] for lb, m in fl) <= F[t])
        M.Add(sum(lb * (x[2 * m] + x[2 * m + 1]) for lb, m in fl) <= T[t])
    objexpr = sum(inst.value[m] * x[2 * m] + (inst.value[m] // 2) * x[2 * m + 1] for m in range(nm))
    M.Maximize(objexpr)
    if a.target is not None:
        M.Add(objexpr >= int(target))
    hint_ok = all(lo_[j] <= x0[j] <= hi_[j] for j in range(2 * nm))
    if hint_ok:
        for j in range(2 * nm):
            M.AddHint(x[j], int(x0[j]))
    S = cp_model.CpSolver()
    S.parameters.max_time_in_seconds = a.time
    S.parameters.num_workers = a.workers
    S.parameters.random_seed = a.seed
    t0 = time.time()

    class CB(cp_model.CpSolverSolutionCallback):
        def on_solution_callback(self):
            print(f"  sol {self.ObjectiveValue():.0f} borne {self.BestObjectiveBound():.0f} ({time.time()-t0:.0f}s)",
                  flush=True)
    st = S.Solve(M, CB())
    print(f"  statut {S.StatusName(st)} valeur {S.ObjectiveValue() if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None}"
          f" borne {S.BestObjectiveBound()} ({time.time()-t0:.0f}s)", flush=True)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return
    xv = [S.Value(v) for v in x]
    out = {"value": S.ObjectiveValue(), "f": [float(xv[2 * m]) for m in range(nm)],
           "h": [float(xv[2 * m + 1]) for m in range(nm)], "y": [0.0] * nm, "z": [[] for _ in range(nm)]}
    with open(a.out or os.path.join(ROOT, "runs", f"fin_roles_{k}_cp.json"), "w") as f:
        json.dump(out, f)


if __name__ == "__main__":
    main()
