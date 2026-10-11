#!/usr/bin/env python3
"""Rematch (src/rematch.py) avec paquets générés AUSSI pour les fenêtres des modèles candidats hors solution.

rematch.py --gen n'échantillonne des paquets que pour les créneaux de la solution courante : un modèle inutilisé
n'entre que si un paquet existant tombe dans ses fenêtres. Ici on ajoute, pour chaque modèle candidat (coût réduit
LP >= -theta) hors solution, ses fenêtres (libres si plein tarif possible, copyrightées sinon) à l'échantillonnage.

Usage : python src/fin_rematch.py <k> [--time 600] [--theta 60] [--gen 20] [--delta 60] [--kbest 30] [--seed 0]
        [--start f] [--save] [--out f]
"""
import argparse
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402
from rematch import (generate_packages, packages_from_solution, candidate_models, build_and_solve,  # noqa: E402
                     reduced_costs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("--start", default=None)
    ap.add_argument("--time", type=float, default=600)
    ap.add_argument("--theta", type=float, default=60)
    ap.add_argument("--gen", type=int, default=20)
    ap.add_argument("--delta", type=int, default=60)
    ap.add_argument("--kbest", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--subsets", action="store_true")
    ap.add_argument("--no-singletons", action="store_true")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    k = a.instance
    inst = Instance(k)
    start = a.start or os.path.join(ROOT, "best", f"instance_{k}.json")
    sol = json.load(open(start))
    lp = json.load(open(os.path.join(ROOT, "runs", f"lp_{k}.json")))
    M, G = candidate_models(inst, lp, a.theta)
    src = {s for s, _ in sol["modelMappings"]}
    used = {m for _, m in sol["dataMappings"]} | src | {t for _, t in sol["modelMappings"]}
    wx = set()
    for m in M:
        if m in used:
            continue
        rq = inst.reqs[m]
        feas = all(lb <= ub for _, lb, ub in rq)
        for t, lb, ub in rq:
            if lb <= ub:
                if feas:
                    wx.add((t, lb, ub, False))
                wx.add((t, lb, ub, True))
    for g in G:
        if g not in used:
            t, lb, ub = rq = inst.reqs[g][0]
            wx.add((t, lb, ub, True))
    gen = generate_packages(inst, sol, a.gen, a.delta, random.Random(a.seed), windows_extra=wx)
    print(f"inst {k}: {len(wx)} fenêtres candidates en plus, {len(gen)} paquets échantillonnés", flush=True)
    packs = packages_from_solution(inst, sol, singletons=not a.no_singletons, subsets=a.subsets, extra=gen)
    keep, pk = {}, {}
    for d, m in sol["dataMappings"]:
        pk.setdefault((m, inst.ds[d][0]), []).append(d)
    for (m, t), ds in pk.items():
        keep.setdefault(tuple(sorted(ds)), set()).add(m)
    for d, m in sol["dataMappings"]:
        (G if m in src else M).add(m)
    for _, m in sol["modelMappings"]:
        M.add(m)
    print(f"  {len(packs)} paquets, {len(M)} modèles, {len(G)} générateurs", flush=True)
    gens_on = src
    cov = {(t, inst.reqs[s][0][0]) for s, t in sol["modelMappings"]}
    trained = (set(m for m, _ in pk) | {t for _, t in sol["modelMappings"]}) - gens_on
    defiled = {m: (any(inst.ds[d][2] for (mm, t), ds in pk.items() if mm == m for d in ds)
                   or any((m, t) in cov for t in range(4))) for m in trained}
    cur = {(tuple(sorted(ds)), m, 1 if m in gens_on else 0): True for (m, t), ds in pk.items()}
    newsol, roles, val, bound = build_and_solve(inst, packs, M, G, a.time, kbest=a.kbest, rc=reduced_costs(inst, lp),
                                                keep=keep, hint=(trained, defiled, cov, gens_on, cur))
    out = a.out or os.path.join(ROOT, "runs", f"fin_rematch_{k}_s{a.seed}.json")
    txt = json.dumps(newsol, separators=(",", ":"))
    with open(out, "w") as f:
        f.write(txt)
    from save_if_better import evaluate, save_if_better
    sc, ok, msg = evaluate(k, txt, inst.txt)
    print(f"  score officiel {sc} valide={ok} {msg} ; MIP {val:.0f} (borne {bound})", flush=True)
    if a.save and ok:
        save_if_better(k, txt, method=f"fin_rematch theta={a.theta} gen={a.gen} delta={a.delta} seed={a.seed}",
                       dataset_txt=inst.txt)


if __name__ == "__main__":
    main()
