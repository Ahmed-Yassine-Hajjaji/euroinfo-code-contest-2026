#!/usr/bin/env python3
"""Choix plein tarif / demi-tarif à ensemble de modèles FIXÉ (instance sans générateurs, ex. 4).

Passer f <-> h ne change pas l'énergie : à modèles utilisés U fixés, maximiser Σ_{m ∈ F} (v - v//2) sous
Σ_{m ∈ F} lb_{m,t} <= offre libre_t (4 types). Sac à dos 4-D exact (HiGHS), hint = best/.
Usage : python src/fin_fh4.py <k> [--time 600] [--start roles.json] [--out runs/fin_roles_k_fh.json]
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
from fin_mip4 import hint_from_best, make  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("--time", type=float, default=600)
    ap.add_argument("--start", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    k = a.instance
    inst = Instance(k)
    nm = len(inst.value)
    if a.start:
        r = json.load(open(a.start))
        x0 = np.zeros(2 * nm)
        for m in range(nm):
            x0[2 * m] = r["f"][m]; x0[2 * m + 1] = r["h"][m]
    else:
        x0 = hint_from_best(inst, k)
    U = [m for m in range(nm) if x0[2 * m] + x0[2 * m + 1] > 0.5]
    F = [0] * 4
    for t, s, c in inst.ds:
        if not c:
            F[t] += s
    n = len(U)
    obj = np.array([-(inst.value[m] - inst.value[m] // 2) for m in U], dtype=float)
    rows, cols, vals = [], [], []
    for i, m in enumerate(U):
        for t, lb, _ in inst.reqs[m]:
            rows.append(t); cols.append(i); vals.append(float(lb))
    A = coo_matrix((vals, (rows, cols)), shape=(4, n)).tocsc()
    ub = np.array([1.0 if all(lb <= u for _, lb, u in inst.reqs[m]) else 0.0 for m in U])
    base = sum(inst.value[m] // 2 for m in U)
    xs0 = np.array([x0[2 * m] for m in U])
    v0 = base - obj @ xs0
    t0 = time.time()
    hl = make(obj, np.zeros(n), ub, A, np.array(F, dtype=float), False, 1)
    hl.run()
    lpb = base - hl.getInfo().objective_function_value
    print(f"inst {k}: |U|={n}, valeur actuelle {v0:.0f}, borne LP à U fixé {lpb:.2f}", flush=True)
    hm = make(obj, np.zeros(n), ub, A, np.array(F, dtype=float), True, 1)
    hm.setOptionValue("time_limit", a.time)
    hm.setOptionValue("mip_rel_gap", 0.0)
    import highspy
    s0 = highspy.HighsSolution(); s0.col_value = list(xs0); hm.setSolution(s0)
    hm.run()
    info = hm.getInfo()
    xs = np.round(np.array(hm.getSolution().col_value))
    val = base - obj @ xs
    use = A @ xs
    print(f"  {hm.modelStatusToString(hm.getModelStatus())} valeur {val:.0f} borne {base - info.mip_dual_bound:.2f} "
          f"marges {[F[t] - use[t] for t in range(4)]} ({time.time()-t0:.0f}s)", flush=True)
    f = [0.0] * nm; h = [0.0] * nm
    for i, m in enumerate(U):
        if xs[i] > .5:
            f[m] = 1.0
        else:
            h[m] = 1.0
    with open(a.out or os.path.join(ROOT, "runs", f"fin_roles_{k}_fh.json"), "w") as fo:
        json.dump({"value": float(val), "f": f, "h": h, "y": [0.0] * nm, "z": [[] for _ in range(nm)]}, fo)


if __name__ == "__main__":
    main()
