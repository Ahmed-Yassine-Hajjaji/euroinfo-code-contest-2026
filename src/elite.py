"""Pool d'élite : parmi des solutions valides de l'instance k, garde les N plus différentes (distance = paquets non
partagés) parmi celles de score >= seuil. Usage : python src/elite.py <k> <N> <seuil> <fichiers...>  -> runs/elite_<k>/e<i>.json"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from greedy import Instance
from save_if_better import evaluate
k, N, seuil = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
inst = Instance(k)
cands = []
for fn in sys.argv[4:]:
    try:
        txt = open(fn).read(); sol = json.loads(txt)
    except Exception:
        continue
    sc, ok, _ = evaluate(k, txt, inst.txt)
    if not ok or sc < seuil:
        continue
    pk = {}
    for d, m in sol["dataMappings"]:
        pk.setdefault((m, inst.ds[d][0]), []).append(d)
    cands.append((sc, fn, frozenset(tuple(sorted(v)) for v in pk.values()), txt))
cands.sort(key=lambda x: -x[0])
print(f"{len(cands)} solutions valides >= {seuil}")
chosen = [cands[0]] if cands else []
while len(chosen) < N and len(chosen) < len(cands):
    # max-min distance, pondérée par le score
    best = max((c for c in cands if c not in chosen), key=lambda c: min(len(c[2] ^ e[2]) for e in chosen) + 0.5 * (c[0] - cands[0][0]) / 10)
    chosen.append(best)
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs", f"elite_{k}")
os.makedirs(out, exist_ok=True)
for i, (sc, fn, pk, txt) in enumerate(chosen):
    open(os.path.join(out, f"e{i}.json"), "w").write(txt)
    dmin = min((len(pk ^ e[2]) for e in chosen if e is not chosen[i]), default=0)
    print(f"  e{i}: {sc} dist_min {dmin} ({os.path.basename(fn)})")
