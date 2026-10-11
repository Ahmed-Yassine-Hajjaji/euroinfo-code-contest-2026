#!/usr/bin/env python3
"""MIP exact des rôles pour une instance SANS générateurs (instance 4) : sac à dos multidimensionnel.

Variables f_m (plein tarif, données libres), h_m (demi-tarif, toutes données), f + h <= 1.
Contraintes : énergie (entiers mis à l'échelle 1e-6), par type Σ lb·f <= offre libre, Σ lb·(f+h) <= offre totale.
Fixation par coût réduit LP : si coût réduit > borne LP - cible, la variable garde sa valeur LP (exact).
HiGHS (highspy), hint = best/, coupure d'objectif à la cible.

Usage : python src/fin_mip4.py <k> [--time 1200] [--target 1031936] [--threads 2] [--out runs/fin_roles_k.json]
Sortie : rôles au format de lp_bound.py (f, h, y, z) → src/fin_realize.py
"""
import argparse
import json
import os
import sys
import time

import numpy as np
from scipy.sparse import coo_matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402


def build(inst):
    nm = len(inst.value)
    F = [0] * 4
    T = [0] * 4
    for t, s, c in inst.ds:
        T[t] += s
        if not c:
            F[t] += s
    feas = [all(lb <= u for _, lb, u in inst.reqs[m]) for m in range(nm)]
    obj = np.zeros(2 * nm)
    ub = np.zeros(2 * nm)
    rows, cols, vals = [], [], []
    for m in range(nm):
        obj[2 * m] = -inst.value[m]; obj[2 * m + 1] = -(inst.value[m] // 2)
        if feas[m]:
            ub[2 * m] = ub[2 * m + 1] = 1
        e = inst.energy[m] * 1e-6
        rows += [0, 0]; cols += [2 * m, 2 * m + 1]; vals += [e, e]
        for t, lb, _ in inst.reqs[m]:
            rows += [1 + t, 5 + t, 5 + t]; cols += [2 * m, 2 * m, 2 * m + 1]; vals += [lb, lb, lb]
        rows += [9 + m, 9 + m]; cols += [2 * m, 2 * m + 1]; vals += [1, 1]
    rhs = np.array([inst.cap * 1e-6] + F + T + [1] * nm, dtype=float)
    A = coo_matrix((vals, (rows, cols)), shape=(9 + nm, 2 * nm)).tocsc()
    return obj, ub, A, rhs


def make(obj, lo, ub, A, rhs, integer, threads):
    import highspy
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("threads", threads)
    lp = highspy.HighsLp()
    lp.num_col_ = len(obj); lp.num_row_ = len(rhs)
    lp.col_cost_ = obj; lp.col_lower_ = lo; lp.col_upper_ = ub
    lp.row_lower_ = np.full(len(rhs), -np.inf); lp.row_upper_ = rhs
    lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    lp.a_matrix_.start_ = A.indptr.astype(np.int32); lp.a_matrix_.index_ = A.indices.astype(np.int32)
    lp.a_matrix_.value_ = A.data
    if integer:
        lp.integrality_ = [highspy.HighsVarType.kInteger] * len(obj)
    h.passModel(lp)
    return h


def hint_from_best(inst, k):
    sol = json.load(open(os.path.join(ROOT, "best", f"instance_{k}.json")))
    x = np.zeros(2 * len(inst.value))
    cp = {}
    for d, m in sol["dataMappings"]:
        cp[m] = cp.get(m, False) or bool(inst.ds[d][2])
    for m, c in cp.items():
        x[2 * m + (1 if c else 0)] = 1
    return x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("--time", type=float, default=1200)
    ap.add_argument("--target", type=float, default=None)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--out", default=None)
    ap.add_argument("--nofix", action="store_true")
    a = ap.parse_args()
    k = a.instance
    inst = Instance(k)
    obj, ub, A, rhs = build(inst)
    lo = np.zeros(len(obj))
    x0 = hint_from_best(inst, k)
    v0 = -obj @ x0
    target = a.target if a.target is not None else v0 + 1
    t0 = time.time()
    hl = make(obj, lo, ub.copy(), A, rhs, False, a.threads)
    hl.run()
    s = hl.getSolution()
    xl = np.array(s.col_value); rc = np.array(s.col_dual)
    bound = -hl.getInfo().objective_function_value
    gapv = bound - target
    nfix = 0
    ubf, lof = ub.copy(), lo.copy()
    if not a.nofix:
        for j in range(len(obj)):
            if ub[j] == 0:
                continue
            # minimisation : rc > 0 au borne inf -> monter coûte rc ; rc < 0 à la borne sup -> descendre coûte -rc
            if xl[j] < 1e-9 and rc[j] > gapv + 1e-6:
                ubf[j] = 0; nfix += 1
            elif xl[j] > 1 - 1e-9 and -rc[j] > gapv + 1e-6:
                lof[j] = 1; nfix += 1
    free = int(((ubf - lof) > 0.5).sum())
    print(f"inst {k}: hint {v0:.0f}, borne LP {bound:.2f}, cible {target:.0f}, fixées {nfix}, libres {free} "
          f"({time.time()-t0:.0f}s)", flush=True)
    hint_ok = bool(np.all(x0 >= lof - 1e-9) and np.all(x0 <= ubf + 1e-9))
    hm = make(obj, lof, ubf, A, rhs, True, a.threads)
    hm.setOptionValue("time_limit", a.time)
    hm.setOptionValue("mip_rel_gap", 0.0)
    hm.setOptionValue("objective_bound", -(target - 0.5))
    if hint_ok:
        import highspy
        sol0 = highspy.HighsSolution(); sol0.col_value = list(x0); hm.setSolution(sol0)
    else:
        print("  hint incompatible avec la fixation (normal si cible > hint)", flush=True)
    hm.run()
    info = hm.getInfo()
    x = np.round(np.array(hm.getSolution().col_value)) if info.primal_solution_status else None
    print(f"  statut {hm.modelStatusToString(hm.getModelStatus())}, valeur "
          f"{(-obj @ x) if x is not None else None}, borne {-info.mip_dual_bound:.1f} ({time.time()-t0:.0f}s)",
          flush=True)
    if x is None:
        return
    nm = len(inst.value)
    E = sum(inst.energy[m] for m in range(nm) if x[2 * m] + x[2 * m + 1] > 0.5)
    print(f"  énergie exacte {E} / {inst.cap} -> {'OK' if E <= inst.cap else 'DÉPASSE'}", flush=True)
    out = {"value": float(-obj @ x), "f": [float(x[2 * m]) for m in range(nm)],
           "h": [float(x[2 * m + 1]) for m in range(nm)], "y": [0.0] * nm, "z": [[] for _ in range(nm)]}
    with open(a.out or os.path.join(ROOT, "runs", f"fin_roles_{k}.json"), "w") as f:
        json.dump(out, f)


if __name__ == "__main__":
    main()
