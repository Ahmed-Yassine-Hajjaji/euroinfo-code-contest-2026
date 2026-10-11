#!/usr/bin/env python3
"""Réalisation d'un fichier de rôles (f, h, y, z) en solution complète (datasets → besoins, générateurs → cibles).

Usage : python src/fin_realize.py <k> <roles.json> [--out f.json] [--save] [--method txt]

Remplissage par type, besoins triés du plus étroit au plus large ; pour chaque besoin : plus petit dataset qui
complète la fenêtre, sinon plus gros qui tient, sinon subset-sum exact (DP) sur les datasets restants.
Plein tarif (f) : datasets libres seulement. Demi-tarif / générateur : copyrightés d'abord.
"""
import argparse
import bisect
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402


class Pool:
    def __init__(self, items):
        self.v = sorted(items)  # (taille, id)

    def take(self, i):
        return self.v.pop(i)

    def fill(self, lb, ub):
        """Liste de (taille, id) de somme dans [lb, ub], ou None (rien n'est retiré en cas d'échec)."""
        got, cur = [], 0
        while cur < lb:
            need, room = lb - cur, ub - cur
            i = bisect.bisect_left(self.v, (need, -1))
            if i < len(self.v) and self.v[i][0] <= room:
                got.append(self.take(i)); cur += got[-1][0]
                break
            j = bisect.bisect_right(self.v, (room, 1 << 60)) - 1
            if j < 0 or len(got) > 40:
                break
            got.append(self.take(j)); cur += got[-1][0]
        if lb <= cur <= ub:
            return got
        for g in got:
            bisect.insort(self.v, g)
        return self.exact(lb, ub)

    def exact(self, lb, ub):
        """Subset-sum exact (bitset) sur les datasets de taille <= ub ; somme minimale >= lb."""
        cand = [x for x in self.v if x[0] <= ub]
        reach = {0: None}
        order = []
        for idx, (s, _) in enumerate(cand):
            new = {}
            for r in reach:
                q = r + s
                if q <= ub and q not in reach and q not in new:
                    new[q] = (r, idx)
            reach.update(new)
            if any(lb <= q <= ub for q in new):
                break
        best = min((q for q in reach if lb <= q <= ub), default=None)
        if best is None:
            return None
        got, q = [], best
        while q:
            r, idx = reach[q]
            got.append(cand[idx]); q = r
        for g in got:
            self.v.remove(g)
        return got


def realize(inst, roles):
    nm = len(inst.value)
    f, h, y, z = roles["f"], roles["h"], roles["y"], roles["z"]
    pools = {}
    for t in range(4):
        pools[(t, 0)] = Pool([(s, i) for i, (tt, s, c) in enumerate(inst.ds) if tt == t and not c])
        pools[(t, 1)] = Pool([(s, i) for i, (tt, s, c) in enumerate(inst.ds) if tt == t and c])
    jobs = []  # (largeur, m, t, lb, ub, libre seulement)
    for m in range(nm):
        role = "f" if f[m] > .5 else "h" if h[m] > .5 else "y" if y[m] > .5 else None
        if role is None:
            continue
        cov = set(z[m]) if role == "h" else set()
        for t, lb, ub in inst.reqs[m]:
            if t not in cov:
                jobs.append((ub - lb, m, t, lb, ub, role == "f"))
    jobs.sort()
    dm, failed = [], set()
    for _, m, t, lb, ub, free in jobs:
        if m in failed:
            continue
        got = pools[(t, 0)].fill(lb, ub) if free else (pools[(t, 1)].fill(lb, ub) or pools[(t, 0)].fill(lb, ub))
        if got is None:
            failed.add(m)
            continue
        dm += [[i, m] for _, i in got]
    # rend les datasets des modèles en échec (ils sont simplement retirés)
    dm = [p for p in dm if p[1] not in failed]
    gens = {t: [m for m in range(nm) if y[m] > .5 and m not in failed and inst.reqs[m][0][0] == t] for t in range(4)}
    mm = []
    for m in range(nm):
        if h[m] > .5 and m not in failed:
            for t in z[m]:
                if not gens[t]:
                    failed.add(m)
                    break
                mm.append([gens[t].pop(), m])
    dm = [p for p in dm if p[1] not in failed]
    mm = [p for p in mm if p[1] not in failed]
    used_src = {s for s, _ in mm}
    # générateurs inutilisés : on les retire (énergie sans valeur)
    dm = [p for p in dm if not (y[p[1]] > .5 and p[1] not in used_src)]
    return {"dataMappings": dm, "modelMappings": mm}, failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("roles")
    ap.add_argument("--out", default=None)
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--method", default="fin_realize")
    a = ap.parse_args()
    inst = Instance(a.instance)
    roles = json.load(open(a.roles))
    sol, failed = realize(inst, roles)
    from save_if_better import evaluate
    txt = json.dumps(sol)
    score, ok, msg = evaluate(a.instance, txt, inst.txt)
    print(f"inst {a.instance}: score {score} valide={ok} échecs={len(failed)} {sorted(failed)[:20]}", flush=True)
    out = a.out or os.path.join(ROOT, "runs", f"fin_realize_{a.instance}.json")
    with open(out, "w") as fo:
        fo.write(txt)
    if a.save and ok:
        from save_if_better import save_if_better
        print(save_if_better(a.instance, txt, method=a.method))


if __name__ == "__main__":
    main()
