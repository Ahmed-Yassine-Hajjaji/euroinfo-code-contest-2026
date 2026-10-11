"""Statistiques d'une solution : générateurs, demi/plein tarif, données utilisées, énergie."""
import json, os, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from greedy import Instance

k = int(sys.argv[1]); path = sys.argv[2] if len(sys.argv) > 2 else f"best/instance_{k}.json"
inst = Instance(k); sol = json.load(open(path))
src = {s: t for s, t in sol["modelMappings"]}
gens_of = Counter(t for s, t in sol["modelMappings"])
dm = {}
for d, m in sol["dataMappings"]:
    dm.setdefault(m, []).append(d)
trained = (set(dm) | set(gens_of)) - set(src)
cr = {m: any(inst.ds[d][2] for d in dm.get(m, [])) for m in trained}
half = {m for m in trained if cr[m] or gens_of[m]}
E = sum(inst.energy[m] for m in trained | set(src))
print(f"inst {k}: entraînés {len(trained)} (plein {len(trained-half)}, demi {len(half)}), générateurs {len(src)}")
print(f"  énergie {E/inst.cap:.4f} du cap ; valeur {sum(inst.value[m]//(2 if m in half else 1) for m in trained)}")
used = Counter(); tot = Counter()
for t, s, c in inst.ds: tot[(t, c)] += s
for d, _ in sol["dataMappings"]:
    t, s, c = inst.ds[d]; used[(t, c)] += s
for t in range(4):
    print(f"  type {'ntic'[t]}: libres {used[(t,0)]/max(tot[(t,0)],1):.2f} utilisés, copyright {used[(t,1)]/max(tot[(t,1)],1):.2f}")
print("  nb générateurs par cible:", sorted(Counter(gens_of.values()).items()))
nreq = Counter(len(inst.reqs[m]) for m in half if gens_of[m])
print("  cibles par nb de besoins:", sorted(nreq.items()))
full_cov = sum(1 for m in trained if gens_of[m] == len(inst.reqs[m]))
print(f"  cibles entièrement couvertes par générateurs: {full_cov}")
ex = [sum(inst.ds[d][1] for d in dm.get(m, []) if inst.ds[d][0] == t) - lb for m in trained for t, lb, ub in inst.reqs[m] if gens_of[m] == 0]
gl = sorted(inst.reqs[g][0][1] for g in src)
print(f"  excès moyen par besoin (modèles sans générateur) {sum(ex)/max(len(ex),1):.1f} ; lb des générateurs méd {gl[len(gl)//2] if gl else '-'}")
mono = [m for m in range(len(inst.value)) if inst.gen_ok[m]]
avail = [m for m in mono if m not in trained and m not in src]
print(f"  mono-modèles réalisables {len(mono)}, inutilisés {len(avail)}")
