"""Diagnostic §4.0 de notes/MIP6_PLAN.md : rejoue la réalisation des rôles d'un fichier (f,h,y,z) et ventile
les échecs (créneaux F non remplis, générateurs sans données) ; gaspillage de best/ par catégorie de créneau.
Usage : python src/diag_roles.py <k> [runs/mipr_k.json]"""
import json, os, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from greedy import Instance
from lns import State, static_priority

k = int(sys.argv[1]); roles = sys.argv[2] if len(sys.argv) > 2 else f"runs/mipr_{k}.json"
inst = Instance(k); nm = len(inst.value)
lp = json.load(open(f"runs/lp_{k}.json")); ro = json.load(open(roles))
prices = {"alpha": lp["dual_energy"], "beta": [0]*4, "gamma": 1.0, "select": "profit",
          "lp": (lp["dual_free"], lp["dual_total"])}
st = State(inst, prices); st.pools.exact = 300
F = [m for m in range(nm) if ro["f"][m] > 0.5]; H = [m for m in range(nm) if ro["h"][m] > 0.5]
Y = [m for m in range(nm) if ro["y"][m] > 0.5]
free = [0]*4; tot = [0]*4; nfree = [0]*4; ntot = [0]*4
for t, s, c in inst.ds:
    tot[t] += s; ntot[t] += 1
    if not c: free[t] += s; nfree[t] += 1
lbF = [0]*4; nF = [0]*4; lbY = [0]*4; nY = [0]*4; lbH = [0]*4; nH = [0]*4; nZ = [0]*4
for m in F:
    for t, lb, ub in inst.reqs[m]: lbF[t] += lb; nF[t] += 1
for g in Y:
    t, lb, ub = inst.reqs[g][0]; lbY[t] += lb; nY[t] += 1
for m in H:
    for t, lb, ub in inst.reqs[m]:
        if t in ro["z"][m]: nZ[t] += 1
        else: lbH[t] += lb; nH[t] += 1
print(f"rôles {roles}: F={len(F)} H={len(H)} Y={len(Y)} valeur agrégée {ro.get('value')}")
print("type | créneaux F (Σlb / offre libre) | créneaux H données (Σlb) | générateurs Y (Σlb) | Σlb total / offre totale | cibles z")
for t in range(4):
    print(f"  {'ntic'[t]} | {nF[t]:4d} ({lbF[t]/1e6:.3f}M / {free[t]/1e6:.3f}M = {lbF[t]/free[t]:.3f}) | {nH[t]:3d} ({lbH[t]/1e6:.3f}M)"
          f" | {nY[t]:4d} ({lbY[t]/1e6:.3f}M) | {(lbF[t]+lbH[t]+lbY[t])/tot[t]:.4f} | {nZ[t]}  ; datasets {ntot[t]} (libres {nfree[t]})")
E = sum(inst.energy[m] for m in F+H+Y) / inst.cap
print(f"énergie des rôles : {E:.4f}")
# --- rejeu de la réalisation (même ordre que lns.py --init lp --roles)
sp = [static_priority(st, m) for m in range(nm)]; mx = max(sp) or 1.0
prio = [ro["f"][m] + ro["h"][m] + 1e-3*sp[m]/mx for m in range(nm)]
order = sorted(range(nm), key=lambda m: -prio[m])
Yset = set(Y); saved = st.avail_gen
st.avail_gen = [[(kk, g) for kk, g in lst if g in Yset] for lst in saved]
st.zset = {m: set(ro["z"][m]) for m in range(nm)}
failF = Counter(); okF = 0; failF_lb = []
for m in order:
    if ro["f"][m] > 0.5:
        if st.try_insert(m, ["full"]): okF += 1
        else:
            for t, lb, ub in inst.reqs[m]: failF[t] += 1
            failF_lb.append((len(inst.reqs[m]), [(lb, ub-lb) for _, lb, ub in inst.reqs[m]]))
print(f"\nphase F : {okF}/{len(F)} insérés ; créneaux des échecs par type {dict(failF)}")
print("  exemples d'échecs (nb besoins, [(lb, largeur)]):", failF_lb[:6])
rem = [[s for s, _ in st.pools.p[t][0]] for t in range(4)]
for t in range(4):
    r = rem[t]; print(f"  libres restants type {'ntic'[t]}: {len(r)} datasets, Σ={sum(r)}, <1000: {sum(1 for s in r if s<1000)}, méd {sorted(r)[len(r)//2] if r else '-'}")
print(f"  énergie {st.energy/inst.cap:.4f} valeur {st.total}")
okH = 0; failH = Counter()
for m in order:
    if ro["h"][m] > 0.5:
        if st.try_insert(m, ["z"]): okH += 1
        else: failH[len(ro["z"][m])] += 1
print(f"phase H : {okH}/{len(H)} insérés ; échecs par nb de besoins-z {dict(failH)} ; énergie {st.energy/inst.cap:.4f} valeur {st.total}")
usedY = sum(1 for g in Y if st.used[g] == 2)
print(f"  générateurs Y utilisés {usedY}/{len(Y)}")
for t in range(4):
    r = [s for c in (0, 1) for s, _ in st.pools.p[t][c]]
    print(f"  restants type {'ntic'[t]}: {len(r)} datasets Σ={sum(r)} ; libres {len(st.pools.p[t][0])} copyr {len(st.pools.p[t][1])}")
# générateurs Y non utilisés : leur lb est-il réalisable avec ce qui reste ?
unused = [g for g in Y if st.used[g] == 0]
lbs = sorted(inst.reqs[g][0][1] for g in unused)
print(f"  Y inutilisés {len(unused)} ; lb quantiles {[lbs[int(q*(len(lbs)-1))] for q in (0,.25,.5,.75,1)] if lbs else '-'}")
# --- gaspillage de best/ par catégorie
sol = json.load(open(f"best/instance_{k}.json"))
src = {s: t for s, t in sol["modelMappings"]}; cov = {(t, inst.reqs[s][0][0]) for s, t in sol["modelMappings"]}
byd = {}
for d, m in sol["dataMappings"]: byd.setdefault(m, []).append(d)
wcat = Counter(); ncat = Counter(); lbcat = Counter()
for m, ds in byd.items():
    fill = Counter(); cr = any(inst.ds[d][2] for d in ds)
    for d in ds: fill[inst.ds[d][0]] += inst.ds[d][1]
    for t, v in fill.items():
        if m in src: cat = "Y"
        elif (m, t) in cov: cat = "Hcouvert"
        elif cr or any((m, tt) in cov for tt in range(4)): cat = "H"
        else: cat = "F"
        lb = inst.reqs[m][[tt for tt, _, _ in inst.reqs[m]].index(t)][1] if cat != "Hcouvert" else 0
        wcat[cat] += v - lb; ncat[cat] += 1; lbcat[cat] += lb
print(f"\nbest/instance_{k}.json : gaspillage par catégorie de créneau (nb, Σ excès, Σ lb, excès moyen)")
for c in ("F", "H", "Hcouvert", "Y"):
    print(f"  {c:9s} {ncat[c]:5d}  {wcat[c]:8d}  {lbcat[c]:10d}  {wcat[c]/max(ncat[c],1):7.1f}")
left = Counter(); 
used = {d for d, _ in sol["dataMappings"]}
for d, (t, s, c) in enumerate(inst.ds):
    if d not in used: left[(t, c)] += s; left[("n", t, c)] += 1
print("  datasets non utilisés par (type, copyright) : Σ taille / nb :", {('ntic'[t], c): (left[(t, c)], left[("n", t, c)]) for t in range(4) for c in (0, 1)})
