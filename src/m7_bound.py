#!/usr/bin/env python3
"""m7 — borne supérieure VALIDE par le MIP des rôles (lb compté comme consommation, offre libre pleine ou réduite).
Usage : python src/m7_bound.py 2 [--shrink S] [--time 150] [--threads 4]"""
import argparse, json, os, sys, time
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance
from m7_roles import Roles
ap = argparse.ArgumentParser(); ap.add_argument("instance", type=int); ap.add_argument("--shrink", type=float, default=0)
ap.add_argument("--time", type=float, default=150); ap.add_argument("--threads", type=int, default=4)
a = ap.parse_args()
inst = Instance(a.instance); R = Roles(inst)
sol = json.load(open(os.path.join(ROOT, "best", f"instance_{a.instance}.json"))); x0 = R.roles_of_solution(sol)
t0 = time.time()
res = R.solve(integer=True, time_limit=a.time, threads=a.threads, hint=x0, shrink=[a.shrink] * 4)
print(f"inst {a.instance} shrink {a.shrink}: MIP rôles valeur {res['value']:.0f} BORNE {res['bound']:.2f} {res['status']} ({time.time()-t0:.0f}s)", flush=True)
