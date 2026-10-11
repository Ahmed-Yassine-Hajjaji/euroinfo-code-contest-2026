#!/usr/bin/env python3
"""Méthode 4 : réparation exacte ciblée (CP-SAT) des créneaux à fort excès, à rôles fixés.

Sous-problème par type : H = créneaux à fort excès (excès >= --excess, bloc de --hblock), P = créneaux partenaires du
même type (--partners, tirés au hasard, moitié parmi ceux qui contiennent un dataset plus petit que l'excès max de H),
plus les datasets libres du type. Variables x[d, s] (dataset d dans le créneau s), un dataset dans au plus un créneau
(sinon libre), fenêtres lb <= somme <= ub, « libre seulement » pour les créneaux plein tarif. Objectif : min consommation
pondérée (poids duaux LP : libre ~ 2x copyrighté) = max taille libérée. Hint = affectation courante. Les rôles et les
modelMappings ne changent pas ; la solution reconstruite est validée par le scoreur officiel.

Usage : python src/m4_cp.py <k> <sol_in> <sol_out> [--excess 200] [--hblock 40] [--partners 200] [--time 60]
        [--workers 4] [--rounds 1] [--seed 0] [--types 0,1,2,3] [--budget 0 (s total, 0 = illimité)]
"""
import argparse
import json
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402
from m3_prep import slots_of  # noqa: E402  (lecture seule)
from save_if_better import evaluate  # noqa: E402


def solve_block(inst, slots, assign, H, P, free_ds, w, time_limit, workers, seed, log, force=0):
    """CP-SAT sur les créneaux H u P avec les datasets qu'ils contiennent + free_ds. Modifie assign en place.
    Retourne (unités libérées, statut)."""
    from ortools.sat.python import cp_model
    S = list(H) + list(P)
    sset = set(S)
    D = [d for d in range(len(inst.ds)) if assign[d] in sset] + list(free_ds)
    m = cp_model.CpModel()
    x = {}
    by_s = {s: [] for s in S}
    by_d = {d: [] for d in D}
    for d in D:
        t, sz, c = inst.ds[d]
        for s in S:
            st, lb, ub, fo, _ = slots[s]
            if st != t or sz > ub or (fo and c):
                continue
            v = m.NewBoolVar(f"x{d}_{s}")
            x[d, s] = v
            by_s[s].append((sz, v))
            by_d[d].append(v)
    for d in D:
        if by_d[d]:
            m.Add(sum(by_d[d]) <= 1)
    for s in S:
        _, lb, ub, _, _ = slots[s]
        expr = sum(sz * v for sz, v in by_s[s])
        m.Add(expr >= lb)
        m.Add(expr <= ub)
    obj = sum(w[d] * inst.ds[d][1] * v for (d, s), v in x.items())
    cur = 0
    for (d, s), v in x.items():
        hv = 1 if assign[d] == s else 0
        m.AddHint(v, hv)
        cur += w[d] * inst.ds[d][1] * hv
    if force:
        m.Add(obj <= cur - force)
    m.Minimize(obj)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = seed
    solver.parameters.linearization_level = 2
    for s_ in S:
        m.Add(sum(v for _, v in by_s[s_]) >= 1)
    t0 = time.time()
    st = solver.Solve(m)
    name = solver.StatusName(st)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        log(f"    bloc |H|={len(H)} |P|={len(P)} |D|={len(D)} vars={len(x)} : {name} ({time.time() - t0:.0f}s)")
        return 0, name
    new = solver.ObjectiveValue()
    if new >= cur - 0.5:
        log(f"    bloc |H|={len(H)} |P|={len(P)} |D|={len(D)} vars={len(x)} : {name} sans gain ({time.time() - t0:.0f}s, "
            f"borne {solver.BestObjectiveBound():.0f} / {cur})")
        return 0, name
    before = sum(inst.ds[d][1] for d in D if assign[d] >= 0)
    for d in D:
        assign[d] = -1
    for (d, s), v in x.items():
        if solver.Value(v):
            assign[d] = s
    after = sum(inst.ds[d][1] for d in D if assign[d] >= 0)
    log(f"    bloc |H|={len(H)} |P|={len(P)} |D|={len(D)} vars={len(x)} : {name} obj {cur} -> {new:.0f} "
        f"(borne {solver.BestObjectiveBound():.0f}), libéré {before - after} u. ({time.time() - t0:.0f}s)")
    return before - after, name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("k", type=int)
    ap.add_argument("sol_in")
    ap.add_argument("sol_out")
    ap.add_argument("--excess", type=int, default=200)
    ap.add_argument("--hblock", type=int, default=40)
    ap.add_argument("--partners", type=int, default=200)
    ap.add_argument("--time", type=float, default=60)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--types", default="0,1,2,3")
    ap.add_argument("--budget", type=float, default=0)
    ap.add_argument("--pmode", choices=["random", "excess", "release"], default="release")
    ap.add_argument("--force", type=int, default=0, help="impose obj <= courant - force (recherche de faisabilité)")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    inst = Instance(a.k)
    sol = json.load(open(a.sol_in))
    slots, assign = slots_of(inst, sol)
    lp = json.load(open(os.path.join(ROOT, "runs", f"lp_{a.k}.json")))
    w = [int(round(1000 * (lp["dual_total"][t] + (lp["dual_free"][t] if not c else 0)))) for t, _, c in inst.ds]
    t_start = time.time()

    def log(msg):
        print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)

    def excess_of():
        s = [0] * len(slots)
        for d, sl in enumerate(assign):
            if sl >= 0:
                s[sl] += inst.ds[d][1]
        return [s[i] - slots[i][1] for i in range(len(slots))]

    ex = excess_of()
    log(f"m4_cp k={a.k} {len(slots)} créneaux, gaspillage {sum(ex)}, libres {sum(1 for x in assign if x < 0)}, "
        f"créneaux excès>={a.excess} : {sum(1 for e in ex if e >= a.excess)}")
    freed_total = 0
    types = [int(t) for t in a.types.split(",")]
    for r in range(a.rounds):
        for t in types:
            if a.budget and time.time() - t_start > a.budget:
                break
            ex = excess_of()
            st = [i for i in range(len(slots)) if slots[i][0] == t]
            hot = sorted([i for i in st if ex[i] >= a.excess], key=lambda i: -ex[i])
            if not hot:
                continue
            # bloc de H : fenêtre glissante aléatoire sur les créneaux chauds
            if len(hot) > a.hblock:
                off = rng.randrange(0, len(hot) - a.hblock + 1)
                H = hot[off:off + a.hblock]
            else:
                H = hot
            emax = max(ex[i] for i in H)
            hs = set(H)
            others = [i for i in st if i not in hs]
            members = {}
            for d, sl in enumerate(assign):
                if sl >= 0:
                    members.setdefault(sl, []).append(inst.ds[d][1])
            if a.pmode == "release":  # partenaires = créneaux à >= 2 datasets remplissables par un seul (lb <= taille max), puis par excès
                smax = max(sz for _, sz, _ in inst.ds)
                others.sort(key=lambda i: (not (len(members.get(i, [])) >= 2 and slots[i][1] <= smax), -ex[i]))
                small = []
            elif a.pmode == "excess":  # partenaires = créneaux suivants par excès décroissant (l'excès absorbe les pertes)
                others.sort(key=lambda i: -ex[i])
                small = []
            else:
                small = [i for i in others if min(members.get(i, [10**9])) <= emax]
                rng.shuffle(small)
                rng.shuffle(others)
            P = small[:a.partners // 2]
            ps = set(P)
            for i in others:
                if len(P) >= a.partners:
                    break
                if i not in ps:
                    P.append(i)
                    ps.add(i)
            free_ds = [d for d in range(len(inst.ds)) if assign[d] < 0 and inst.ds[d][0] == t]
            log(f"  tour {r + 1} type {t} : {len(hot)} créneaux chauds (excès max {emax}), bloc {len(H)}, {len(P)} partenaires, "
                f"{len(free_ds)} libres")
            freed, _ = solve_block(inst, slots, assign, H, P, free_ds, w, a.time, a.workers, a.seed + 7 * r + t, log, a.force)
            freed_total += freed
    ex = excess_of()
    dm = [[d, slots[sl][4]] for d, sl in enumerate(assign) if sl >= 0]
    new = {"dataMappings": dm, "modelMappings": sol["modelMappings"]}
    txt = json.dumps(new)
    score, ok, msg = evaluate(a.k, txt)
    ref = evaluate(a.k, open(a.sol_in).read())[0]
    if ok and score >= ref:
        with open(a.sol_out, "w") as f:
            f.write(txt)
    else:
        log(f"solution invalide ou moins bonne ({score} vs {ref}, {msg}) : on écrit la solution d'entrée")
        with open(a.sol_out, "w") as f:
            f.write(open(a.sol_in).read())
    log(f"FIN : score {score} (réf {ref}) valide={ok} gaspillage {sum(ex)} libres {sum(1 for x in assign if x < 0)} "
        f"libéré {freed_total} u. en {time.time() - t_start:.0f}s -> {a.sol_out}")


if __name__ == "__main__":
    main()
