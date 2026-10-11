#!/usr/bin/env python3
"""Applique localement un changement de tarifs (rôles cibles de fin_fh.py) à la meilleure solution.

Modèles qui changent (h -> f ou f -> h) : leurs datasets sont libérés ; on remplit leurs nouveaux créneaux par
subset-sum exact (ordre décroissant) : plein tarif depuis les libres libérés (+ libres inutilisés), demi-tarif
depuis copyrightés libérés/inutilisés puis libres restants. Les modèles en échec gardent leur ancien tarif
(et leurs datasets) et on recommence. Validation officielle + save_if_better.

Usage : python src/fin_switch.py <k> <roles_cibles.json> [--start sol.json] [--save] [--tries 30] [--seed 0]
"""
import argparse
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402
from fin_fh import roles_of  # noqa: E402
from save_if_better import evaluate, save_if_better  # noqa: E402


def subset_exact(items, lb, ub):
    """items = [(taille, id)] ; somme minimale dans [lb, ub] ; préfère les gros (ordre décroissant)."""
    items = sorted((x for x in items if x[0] <= ub), key=lambda x: -x[0])
    mask = (1 << (ub + 1)) - 1
    reach = 1
    hist = [1]
    for s, _ in items:
        reach = (reach | (reach << s)) & mask
        hist.append(reach)
    hi = reach >> lb
    if not hi:
        return None
    cur = lb + ((hi & -hi).bit_length() - 1)
    out = []
    for j in range(len(items) - 1, -1, -1):
        if cur == 0:
            break
        if not (hist[j] >> cur) & 1:
            out.append(items[j]); cur -= items[j][0]
    return out


def attempt(inst, sol, r0, r1, S, rng):
    by_m = {}
    for d, m in sol["dataMappings"]:
        by_m.setdefault(m, []).append(d)
    used = {d for d, _ in sol["dataMappings"]}
    pool = {(t, c): [] for t in range(4) for c in (0, 1)}
    for d, (t, s, c) in enumerate(inst.ds):
        if d not in used:
            pool[(t, int(c))].append((s, d))
    for m in S:
        for d in by_m.get(m, []):
            t, s, c = inst.ds[d]
            pool[(t, int(c))].append((s, d))
    newmap = {}
    fail = set()
    Sf = [m for m in S if r1["f"][m]]
    Sh = [m for m in S if r1["h"][m]]
    rng.shuffle(Sf); rng.shuffle(Sh)
    # plein tarif d'abord (fenêtres les plus étroites d'abord)
    for group, full in ((Sf, True), (Sh, False)):
        for m in group:
            taken = []
            ok = True
            for t, lb, ub in sorted(inst.reqs[m], key=lambda r: r[2] - r[1]):
                if t in r1["z"][m]:
                    continue
                got = None
                if full:
                    got = subset_exact(pool[(t, 0)], lb, ub)
                    if got:
                        for g in got:
                            pool[(t, 0)].remove(g)
                        taken += [(t, 0, g) for g in got]
                else:
                    got = subset_exact(pool[(t, 1)], lb, ub)
                    if got:
                        for g in got:
                            pool[(t, 1)].remove(g)
                        taken += [(t, 1, g) for g in got]
                    else:
                        got = subset_exact(pool[(t, 1)] + pool[(t, 0)], lb, ub)
                        if got:
                            for g in got:
                                c = int(inst.ds[g[1]][2])
                                pool[(t, c)].remove(g)
                                taken.append((t, c, g))
                if not got:
                    ok = False
                    break
            if not ok:
                for t, c, g in taken:
                    pool[(t, c)].append(g)
                fail.add(m)
            else:
                newmap[m] = [g[1] for _, _, g in taken]
    return newmap, fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("roles")
    ap.add_argument("--start", default=None)
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--tries", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    k = a.instance
    inst = Instance(k)
    sol = json.load(open(a.start or os.path.join(ROOT, "best", f"instance_{k}.json")))
    r0 = roles_of(inst, sol)
    r1 = json.load(open(a.roles))
    nm = len(inst.value)
    S0 = {m for m in range(nm) if (r0["f"][m] != r1["f"][m] or r0["h"][m] != r1["h"][m])
          and (r0["f"][m] or r0["h"][m]) and (r1["f"][m] or r1["h"][m])}
    print(f"inst {k}: {len(S0)} changements de tarif", flush=True)
    base_sc = evaluate(k, json.dumps(sol), inst.txt)[0]
    rng = random.Random(a.seed)
    best_sc, best_txt = base_sc, None
    for tr in range(a.tries):
        S = set(S0)
        for _ in range(20):
            newmap, fail = attempt(inst, sol, r0, r1, S, rng)
            if not fail:
                break
            S -= fail
        dm = [[d, m] for d, m in sol["dataMappings"] if m not in S]
        for m, ds in newmap.items():
            dm += [[d, m] for d in ds]
        txt = json.dumps({"dataMappings": dm, "modelMappings": sol["modelMappings"]})
        sc, ok, msg = evaluate(k, txt, inst.txt)
        print(f"  essai {tr}: {len(S)}/{len(S0)} changements appliqués -> {sc} valide={ok} {msg}", flush=True)
        if ok and sc > best_sc:
            best_sc, best_txt = sc, txt
    print(f"meilleur {best_sc} (départ {base_sc})", flush=True)
    if best_txt:
        with open(os.path.join(ROOT, "runs", f"fin_switch_{k}.json"), "w") as f:
            f.write(best_txt)
        if a.save:
            save_if_better(k, best_txt, method=f"fin_switch tarifs f/h exacts ({os.path.basename(a.roles)})")


if __name__ == "__main__":
    main()
