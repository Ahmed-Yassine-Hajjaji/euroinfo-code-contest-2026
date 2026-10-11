#!/usr/bin/env python3
"""Choix plein / demi-tarif à modèles utilisés FIXÉS, instances avec générateurs (2, 5...) ou sans (4).

Rôles extraits d'une solution : y = sources, z = besoins couverts des cibles (cibles figées en demi-tarif).
Pour les autres modèles utilisés (non cibles, non sources) : f ou h. f <-> h ne change ni l'énergie ni la
consommation totale (lb), seulement la consommation de données libres : sac à dos 4-D exact (HiGHS).
Les besoins d'un modèle h, d'un générateur y comptent en données totales ; un f compte en libres.
Sortie : fichier de rôles (f, h, y, z) pour lns.py --init lp --roles ... --exact N.
Usage : python src/fin_fh.py <k> [--start sol.json] [--time 600] [--shrink 0] [--out runs/fin_roles_k_fh.json]
  --shrink : marge (unités) retirée de l'offre libre par type (anticipation du gaspillage de réalisation)
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
from fin_mip4 import make  # noqa: E402


def roles_of(inst, sol):
    nm = len(inst.value)
    src = {s for s, _ in sol["modelMappings"]}
    z = [[] for _ in range(nm)]
    for s, t in sol["modelMappings"]:
        z[t].append(inst.reqs[s][0][0])
    cp = {}
    for d, m in sol["dataMappings"]:
        cp[m] = cp.get(m, False) or bool(inst.ds[d][2])
    used = set(cp) | src | {t for _, t in sol["modelMappings"]}
    f = [0.0] * nm; h = [0.0] * nm; y = [0.0] * nm
    for m in used:
        if m in src:
            y[m] = 1.0
        elif cp.get(m) or z[m]:
            h[m] = 1.0
        else:
            f[m] = 1.0
    return {"f": f, "h": h, "y": y, "z": z}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("--start", default=None)
    ap.add_argument("--time", type=float, default=600)
    ap.add_argument("--shrink", type=float, default=0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--keep-use", type=float, default=None, help="offre libre = consommation lb actuelle + X par type")
    ap.add_argument("--roles-only", action="store_true", help="écrit seulement les rôles de la solution (sans MIP)")
    a = ap.parse_args()
    k = a.instance
    inst = Instance(k)
    nm = len(inst.value)
    sol = json.load(open(a.start or os.path.join(ROOT, "best", f"instance_{k}.json")))
    ro = roles_of(inst, sol)
    out = a.out or os.path.join(ROOT, "runs", f"fin_roles_{k}_fh.json")
    if a.roles_only:
        json.dump(ro, open(out, "w"))
        return
    F = [0] * 4
    for t, s, c in inst.ds:
        if not c:
            F[t] += s
    U = [m for m in range(nm) if (ro["f"][m] or ro["h"][m]) and not ro["z"][m]
         and all(lb <= u for _, lb, u in inst.reqs[m])]
    n = len(U)
    obj = np.array([-(inst.value[m] - inst.value[m] // 2) for m in U], dtype=float)
    rows, cols, vals = [], [], []
    for i, m in enumerate(U):
        for t, lb, _ in inst.reqs[m]:
            rows.append(t); cols.append(i); vals.append(float(lb))
    A = coo_matrix((vals, (rows, cols)), shape=(4, n)).tocsc()
    rhs = np.array([F[t] - a.shrink for t in range(4)], dtype=float)
    if a.keep_use is not None:
        rhs = np.array(A @ np.array([ro["f"][m] for m in U]) + a.keep_use, dtype=float)
    base = sum(inst.value[m] // 2 for m in U)
    other = sum(inst.value[m] // 2 for m in range(nm) if ro["z"][m] and ro["h"][m])
    xs0 = np.array([ro["f"][m] for m in U])
    use0 = A @ xs0
    print(f"inst {k}: |U|={n}, libres utilisés (lb) {[int(u) for u in use0]} / offre {F}", flush=True)
    t0 = time.time()
    hm = make(obj, np.zeros(n), np.ones(n), A, rhs, True, 1)
    hm.setOptionValue("time_limit", a.time)
    hm.setOptionValue("mip_rel_gap", 0.0)
    import highspy
    if np.all(use0 <= rhs):
        s0 = highspy.HighsSolution(); s0.col_value = list(xs0); hm.setSolution(s0)
    hm.run()
    info = hm.getInfo()
    xs = np.round(np.array(hm.getSolution().col_value))
    use = A @ xs
    print(f"  {hm.modelStatusToString(hm.getModelStatus())} : valeur f/h {base - obj @ xs0:.0f} -> {base - obj @ xs:.0f}"
          f" (borne {base - info.mip_dual_bound:.1f}) ; total rôles {other + base - obj @ xs:.0f} ; "
          f"marges {[int(F[t] - use[t]) for t in range(4)]} ({time.time()-t0:.0f}s)", flush=True)
    for i, m in enumerate(U):
        ro["f"][m] = float(xs[i] > .5); ro["h"][m] = float(xs[i] <= .5)
    json.dump(ro, open(out, "w"))


if __name__ == "__main__":
    main()
