"""Gaspillage d'une solution ventilé : fraction de l'offre libre perdue sur les créneaux plein tarif (wf) et fraction
de l'offre totale perdue au total (wt), au format 'wf wt' (entrées de lp_bound.py --shrink). Usage : <k> <sol.json>"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from greedy import Instance
k = int(sys.argv[1]); inst = Instance(k); sol = json.load(open(sys.argv[2]))
src = {s for s, _ in sol["modelMappings"]}; cov = {(t, inst.reqs[s][0][0]) for s, t in sol["modelMappings"]}
byd = {}
for d, m in sol["dataMappings"]: byd.setdefault(m, []).append(d)
free = sum(s for _, s, c in inst.ds if not c); tot = sum(s for _, s, _ in inst.ds)
wF = wT = 0
for m, ds in byd.items():
    fill = {}
    for d in ds: fill[inst.ds[d][0]] = fill.get(inst.ds[d][0], 0) + inst.ds[d][1]
    full = m not in src and not any(inst.ds[d][2] for d in ds) and not any((m, t) in cov for t in range(4))
    for t, v in fill.items():
        lb = 0 if (m, t) in cov else next(lb for tt, lb, _ in inst.reqs[m] if tt == t)
        wT += v - lb
        if full: wF += v - lb
print(f"{wF/free:.5f} {wT/tot:.5f}")
