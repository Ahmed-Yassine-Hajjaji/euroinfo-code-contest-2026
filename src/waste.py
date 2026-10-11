"""Gaspillage de données d'une solution : excès au-delà de lb + données données à un besoin couvert par générateur."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from greedy import Instance


def waste(inst, sol):
    cov = {(t, inst.reqs[s][0][0]) for s, t in sol["modelMappings"]}
    fill = {}
    for d, m in sol["dataMappings"]:
        t, s, c = inst.ds[d]
        fill[(m, t)] = fill.get((m, t), 0) + s
    w = 0
    for (m, t), v in fill.items():
        w += v if (m, t) in cov else v - next(lb for tt, lb, _ in inst.reqs[m] if tt == t)
    return w, sum(fill.values())


if __name__ == "__main__":
    k = int(sys.argv[1])
    inst = Instance(k)
    for p in sys.argv[2:] or [f"best/instance_{k}.json"]:
        w, tot = waste(inst, json.load(open(p)))
        print(f"inst {k} {p}: gaspillage {w} / {tot} utilisées = {100*w/max(tot,1):.3f}% "
              f"(offre {sum(s for _, s, _ in inst.ds)})")
