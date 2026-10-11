#!/usr/bin/env python3
"""Descente par blocs exacts sur les rôles (instance sans générateurs, ex. 4), HiGHS, hint = solution courante.

Pas (a) « tarifs » : modèles utilisés U figés comme utilisés-ou-non, choix f/h/0 parmi U seulement (énergie ne
                     peut que baisser ; sac à dos 4-D sur les données libres).
Pas (b) « énergie » : plein tarif seulement parmi F actuel (f/h/0), tous les autres modèles h/0 (sac à dos énergie).
Pas (c) « LNS »    : q modèles aléatoires totalement libres, les autres figés.
Usage : python src/fin_alt4.py <k> [--rounds 20] [--sub-time 120] [--q 400] [--seed 1] [--start roles.json]
Sortie : runs/fin_alt_roles_<k>.json à chaque amélioration (à réaliser avec lns.py --init lp --roles ... --exact 100000)
"""
import argparse
import json
import os
import random
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402
from fin_mip4 import build, make, hint_from_best  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--sub-time", type=float, default=120)
    ap.add_argument("--q", type=int, default=400)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--start", default=None)
    ap.add_argument("--steps", default="abc")
    ap.add_argument("--gapfix", type=float, default=0, help="pas c : tirage dans le cœur |coût réduit| <= gapfix (0 = tous)")
    a = ap.parse_args()
    k = a.instance
    rng = random.Random(a.seed)
    inst = Instance(k)
    nm = len(inst.value)
    obj, ub, A, rhs = build(inst)
    if a.start:
        r = json.load(open(a.start))
        x = np.array([v for m in range(nm) for v in (r["f"][m], r["h"][m])], dtype=float)
    else:
        x = hint_from_best(inst, k)
    val = lambda x: float(-obj @ x)  # noqa: E731
    E = lambda x: sum(inst.energy[m] for m in range(nm) if x[2 * m] + x[2 * m + 1] > .5)  # noqa: E731
    out = os.path.join(ROOT, "runs", f"fin_alt_roles_{k}.json")
    print(f"inst {k}: départ {val(x):.0f}", flush=True)
    import highspy
    pool = list(range(nm))
    if a.gapfix > 0:
        hl = make(obj, np.zeros(2 * nm), ub.copy(), A, rhs, False, 1)
        hl.run()
        rc = np.abs(np.array(hl.getSolution().col_dual))
        pool = [m for m in range(nm) if ub[2 * m] > 0 and min(rc[2 * m], rc[2 * m + 1]) <= a.gapfix]
        print(f"  cœur : {len(pool)} modèles", flush=True)
    stale = 0
    for rd in range(a.rounds):
        for step in a.steps:
            lo = np.zeros(2 * nm); hi = ub.copy()
            if step == "a":
                for m in range(nm):
                    if x[2 * m] + x[2 * m + 1] < .5:
                        hi[2 * m] = hi[2 * m + 1] = 0
            elif step == "b":
                for m in range(nm):
                    if x[2 * m] < .5:
                        hi[2 * m] = 0
            else:
                R = set(rng.sample(pool, min(a.q, len(pool))))
                for m in range(nm):
                    if m not in R:
                        lo[2 * m] = hi[2 * m] = x[2 * m]; lo[2 * m + 1] = hi[2 * m + 1] = x[2 * m + 1]
            t0 = time.time()
            h = make(obj, lo, hi, A, rhs, True, 1)
            h.setOptionValue("time_limit", a.sub_time)
            h.setOptionValue("mip_rel_gap", 0.0)
            s0 = highspy.HighsSolution(); s0.col_value = list(x); h.setSolution(s0)
            h.run()
            if not h.getInfo().primal_solution_status:
                continue
            xn = np.round(np.array(h.getSolution().col_value))
            vn = val(xn)
            ok = E(xn) <= inst.cap and np.all(A @ xn <= rhs + 1e-9)
            status = h.modelStatusToString(h.getModelStatus())
            print(f"  tour {rd} pas {step}: {vn:.0f} ({status}, {time.time()-t0:.0f}s){'' if ok else ' INFAISABLE exact'}",
                  flush=True)
            if ok and vn > val(x) + 0.5:
                x = xn
                stale = 0
                with open(out, "w") as f:
                    json.dump({"value": vn, "f": [float(x[2 * m]) for m in range(nm)],
                               "h": [float(x[2 * m + 1]) for m in range(nm)], "y": [0.0] * nm,
                               "z": [[] for _ in range(nm)]}, f)
                print(f"  ** amélioration {vn:.0f} -> {out}", flush=True)
            elif ok and np.any(xn != x) and abs(vn - val(x)) < 0.5:
                x = xn  # plateau : on bouge quand même
            else:
                stale += 1


if __name__ == "__main__":
    main()
