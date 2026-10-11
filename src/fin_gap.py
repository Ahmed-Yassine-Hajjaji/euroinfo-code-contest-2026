#!/usr/bin/env python3
"""Décomposition de l'écart LP d'une solution (instance sans générateurs) : coûts réduits + coût des marges.
Usage : python src/fin_gap.py <k> [solution.json]"""
import json
import os
import sys

import numpy as np
from scipy.optimize import linprog

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from greedy import Instance  # noqa: E402
from fin_mip4 import build, hint_from_best  # noqa: E402

k = int(sys.argv[1])
inst = Instance(k)
obj, ub, A, rhs = build(inst)
res = linprog(obj, A_ub=A.tocsr(), b_ub=rhs, bounds=list(zip([0.0] * len(obj), ub)), method="highs")
rc = res.lower.marginals + res.upper.marginals
du = -res.ineqlin.marginals
x = hint_from_best(inst, k) if len(sys.argv) < 3 else None
v = -obj @ x
use = A @ x
sl = rhs - use
names = ["E"] + [f"F{t}" for t in range(4)] + [f"T{t}" for t in range(4)]
print("borne", -res.fun, "valeur", v, "écart", -res.fun - v)
for i in range(9):
    print(f"  {names[i]} dual {du[i]:.3e} marge {sl[i]:.4g} coût {du[i]*sl[i]:.3f}")
gub = du[9:]
print("  coût GUB (marges f+h<=1)", float(gub @ sl[9:]))
print("  coût réduits des écarts au LP", float(sum(abs(rc[j]) for j in range(len(obj)) if abs(x[j] - res.x[j]) > 0.5 and abs(rc[j]) > 1e-9)))
print("  frac LP", int(((res.x > 1e-6) & (res.x < 1 - 1e-6)).sum()))
