"""m6 (mémétique) : utilitaires communs. Paquets d'une solution, distance, population sur disque (verrou fcntl).

Population : runs/m6_pop/pop.json = {"members": [{"id", "file", "score", "origin", "gen"}], "next_id", "stats"}.
Distance entre deux solutions = nombre de paquets non partagés (paquet = ensemble des datasets d'un créneau (modèle, type)),
comme src/elite.py.
"""
import fcntl
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402

POP_DIR = os.path.join(ROOT, "runs", "m6_pop")
POP_FILE = os.path.join(POP_DIR, "pop.json")
LOCK_FILE = os.path.join(POP_DIR, ".lock")


def packs_of(inst, sol):
    """{(modèle, type): tuple triée des datasets}"""
    pk = {}
    for d, m in sol["dataMappings"]:
        pk.setdefault((m, inst.ds[d][0]), []).append(d)
    return {k: tuple(sorted(v)) for k, v in pk.items()}


def pack_set(inst, sol):
    return frozenset(packs_of(inst, sol).values())


def distance(ps1, ps2):
    return len(ps1 ^ ps2)


def waste_of(inst, sol):
    """Gaspillage total (somme - lb sur tous les créneaux remplis par des datasets, hors types couverts par générateur)."""
    cov = {(t, inst.reqs[s][0][0]) for s, t in sol["modelMappings"]}
    w = 0
    for (m, t), ds in packs_of(inst, sol).items():
        if (m, t) in cov:
            w += sum(inst.ds[d][1] for d in ds)
            continue
        lb = next(lb for tt, lb, _ in inst.reqs[m] if tt == t)
        w += sum(inst.ds[d][1] for d in ds) - lb
    return w


class Lock:
    def __init__(self, path=LOCK_FILE):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path

    def __enter__(self):
        self.f = open(self.path, "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def load_pop():
    if not os.path.exists(POP_FILE):
        return {"members": [], "next_id": 0, "stats": {"children": 0, "beat_parent": 0, "inserted": 0, "best_child": 0}}
    with open(POP_FILE) as f:
        return json.load(f)


def save_pop(pop):
    tmp = POP_FILE + f".tmp{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(pop, f, indent=1)
    os.replace(tmp, POP_FILE)


def member_path(mid):
    return os.path.join(POP_DIR, f"p{mid}.json")
