#!/usr/bin/env python3
"""m6 : construit / affiche la population initiale. Usage :
  python src/m6_pool.py init <k> <N> <dmin> <fichiers...>   : valide, dédoublonne (distance < dmin -> garde le meilleur),
                                                             garde les N meilleurs -> runs/m6_pop/
  python src/m6_pool.py show <k>                             : liste la population et la matrice des distances (résumé)
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m6_common import Instance, pack_set, distance, waste_of, Lock, load_pop, save_pop, member_path, POP_DIR  # noqa
from save_if_better import evaluate  # noqa


def init(k, N, dmin, files):
    inst = Instance(k)
    cands = []
    for fn in files:
        try:
            txt = open(fn).read(); sol = json.loads(txt)
        except Exception:
            continue
        sc, ok, _ = evaluate(k, txt, inst.txt)
        if not ok:
            print(f"  {fn}: invalide, ignoré"); continue
        cands.append((sc, fn, pack_set(inst, sol), txt, waste_of(inst, sol)))
    cands.sort(key=lambda x: -x[0])
    chosen = []
    for c in cands:
        if any(distance(c[2], e[2]) < dmin for e in chosen):
            continue
        chosen.append(c)
        if len(chosen) >= N:
            break
    os.makedirs(POP_DIR, exist_ok=True)
    with Lock():
        pop = load_pop()
        pop["members"] = []
        for sc, fn, ps, txt, w in chosen:
            mid = pop["next_id"]; pop["next_id"] += 1
            open(member_path(mid), "w").write(txt)
            pop["members"].append({"id": mid, "file": member_path(mid), "score": sc, "origin": os.path.basename(fn), "gen": 0, "waste": w})
        save_pop(pop)
    print(f"{len(cands)} candidats valides, {len(chosen)} retenus (dmin={dmin})")
    show(k, inst)


def add(k, dmin, files):
    """Ajoute des solutions à la population existante (dédoublonnage par distance)."""
    inst = Instance(k)
    with Lock():
        pop = load_pop()
        P = [pack_set(inst, json.load(open(m["file"]))) for m in pop["members"]]
        n = 0
        for fn in files:
            txt = open(fn).read(); sol = json.loads(txt)
            sc, ok, _ = evaluate(k, txt, inst.txt)
            ps = pack_set(inst, sol)
            if not ok or any(distance(ps, q) < dmin for q in P):
                continue
            mid = pop["next_id"]; pop["next_id"] += 1
            open(member_path(mid), "w").write(txt)
            pop["members"].append({"id": mid, "file": member_path(mid), "score": sc, "origin": os.path.basename(fn), "gen": 0, "waste": waste_of(inst, sol)})
            P.append(ps); n += 1
        save_pop(pop)
    print(f"{n} ajoutés")
    show(k, inst)


def show(k, inst=None):
    inst = inst or Instance(k)
    pop = load_pop()
    ms = pop["members"]
    P = {m["id"]: pack_set(inst, json.load(open(m["file"]))) for m in ms}
    print(f"population {len(ms)} ; stats {pop['stats']}")
    for m in sorted(ms, key=lambda x: -x["score"]):
        ds = sorted(distance(P[m["id"]], P[o["id"]]) for o in ms if o["id"] != m["id"])
        print(f"  p{m['id']:<4} {m['score']} gasp {m.get('waste', '?'):>7} gen {m['gen']:<2} {m['origin'][:28]:<28} dist min/méd {ds[0] if ds else '-'}/{ds[len(ds)//2] if ds else '-'}")


if __name__ == "__main__":
    if sys.argv[1] == "init":
        init(int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5:])
    elif sys.argv[1] == "add":
        add(int(sys.argv[2]), int(sys.argv[3]), sys.argv[4:])
    else:
        show(int(sys.argv[2]))
