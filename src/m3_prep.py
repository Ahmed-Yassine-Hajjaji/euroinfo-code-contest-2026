#!/usr/bin/env python3
"""Méthode 3 (tabou sur l'affectation des datasets, rôles fixés). Pont entre les solutions JSON et le binaire Rust
src/m3_tabu.

  prep    <k> <sol.json> <out.in>                : créneaux + datasets de la solution -> fichier texte pour m3_tabu
  rebuild <k> <sol_ref.json> <assign.out> <sol_out.json> : affectation (dataset -> créneau) -> solution JSON (mêmes
                                                   rôles et modelMappings que sol_ref), validée par le scoreur officiel.
Format .in : ligne 1 "ND NS" ; ligne 2 : 8 poids (w_free[t] w_copy[t], unités LP x 1e6) ; ND lignes "type size free slot"
(slot = -1 si libre) ; NS lignes "type lb ub free_only model".
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402


def slots_of(inst, sol):
    """Liste des créneaux [(type, lb, ub, free_only, model)] et affectation dataset -> indice de créneau (-1 libre)."""
    src = {s: t for s, t in sol["modelMappings"]}
    cov = {(t, inst.reqs[s][0][0]) for s, t in sol["modelMappings"]}
    byd = {}
    for d, m in sol["dataMappings"]:
        byd.setdefault(m, []).append(d)
    trained = (set(byd) | set(src.values())) - set(src)
    slots, where = [], {}
    for m in sorted(trained):
        ds = byd.get(m, [])
        full = not any(inst.ds[d][2] for d in ds) and not any((m, t) in cov for t in range(4))
        for t, lb, ub in inst.reqs[m]:
            if (m, t) in cov:
                continue
            where[(m, t)] = len(slots)
            slots.append((t, lb, ub, 1 if full else 0, m))
    for g in sorted(src):
        t, lb, ub = inst.reqs[g][0]
        where[(g, t)] = len(slots)
        slots.append((t, lb, ub, 0, g))
    assign = [-1] * len(inst.ds)
    for d, m in sol["dataMappings"]:
        assign[d] = where[(m, inst.ds[d][0])]
    return slots, assign


def prep(k, sol_path, out):
    inst = Instance(k)
    sol = json.load(open(sol_path))
    slots, assign = slots_of(inst, sol)
    lp = json.load(open(os.path.join(ROOT, "runs", f"lp_{k}.json")))
    wf = [int(round((lp["dual_free"][t] + lp["dual_total"][t]) * 1e6)) for t in range(4)]
    wc = [int(round(lp["dual_total"][t] * 1e6)) for t in range(4)]
    with open(out, "w") as f:
        f.write(f"{len(inst.ds)} {len(slots)}\n")
        f.write(" ".join(map(str, wf + wc)) + "\n")
        for d, (t, s, c) in enumerate(inst.ds):
            f.write(f"{t} {s} {0 if c else 1} {assign[d]}\n")
        for t, lb, ub, fo, m in slots:
            f.write(f"{t} {lb} {ub} {fo} {m}\n")
    waste = sum(sum(inst.ds[d][1] for d in range(len(inst.ds)) if assign[d] == i) - lb for i, (_, lb, _, _, _) in enumerate(slots))
    print(f"m3_prep: {len(slots)} créneaux, {sum(1 for a in assign if a < 0)} datasets libres, gaspillage {waste}")


def rebuild(k, ref_path, assign_path, out):
    from save_if_better import evaluate
    inst = Instance(k)
    sol = json.load(open(ref_path))
    slots, _ = slots_of(inst, sol)
    assign = [int(x) for x in open(assign_path).read().split()]
    assert len(assign) == len(inst.ds)
    dm = [[d, slots[a][4]] for d, a in enumerate(assign) if a >= 0]
    new = {"dataMappings": dm, "modelMappings": sol["modelMappings"]}
    txt = json.dumps(new)
    score, ok, msg = evaluate(k, txt)
    ref_score = evaluate(k, open(ref_path).read())[0]
    with open(out, "w") as f:
        f.write(txt)
    waste = 0
    for i, (_, lb, _, _, _) in enumerate(slots):
        waste += sum(inst.ds[d][1] for d, a in enumerate(assign) if a == i) - lb
    print(f"m3_rebuild: score {score} (réf {ref_score}) valide={ok} {msg if not ok else ''} gaspillage {waste} "
          f"libres {sum(1 for a in assign if a < 0)} -> {out}")
    return 0 if ok and score >= ref_score else 2


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "prep":
        prep(int(sys.argv[2]), sys.argv[3], sys.argv[4])
    elif cmd == "rebuild":
        sys.exit(rebuild(int(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]))
