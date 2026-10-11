#!/usr/bin/env python3
"""LNS « ré-empaquetage des données libres + insertion de mono-modèles » (CP-SAT, 1 worker).

Un créneau plein tarif = besoin (m, t) d'un modèle non dévalué : il n'utilise que des datasets libres.
À chaque itération : type t, bloc B de créneaux plein tarif de type t (+ datasets libres inutilisés de type t),
candidats C = mono-modèles inutilisés de type t. CP-SAT réaffecte exactement les datasets du bloc :
créneaux des modèles multi-besoins obligatoires, mono-modèles du bloc et candidats optionnels (valeur pleine),
énergie respectée. Objectif : valeur, puis consommation minimale (les restes servent aux blocs suivants).

Usage : python src/fin_pack.py <k> [--time 1800] [--seed 1] [--block 40] [--cand 30] [--sub-time 10] [--save]
"""
import argparse
import json
import os
import random
import sys
import time

from ortools.sat.python import cp_model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402
from save_if_better import evaluate, save_if_better  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("--time", type=float, default=1800)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--block", type=int, default=40)
    ap.add_argument("--cand", type=int, default=30)
    ap.add_argument("--sub-time", type=float, default=10.0)
    ap.add_argument("--start", default=None)
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--save-every", type=float, default=60)
    a = ap.parse_args()
    k = a.instance
    rng = random.Random(a.seed)
    inst = Instance(k)
    nm = len(inst.value)
    sol = json.load(open(a.start or os.path.join(ROOT, "best", f"instance_{k}.json")))
    src = {s for s, _ in sol["modelMappings"]}
    tgt = {t for _, t in sol["modelMappings"]}
    used_models = {m for _, m in sol["dataMappings"]} | src | tgt
    cpy = {}
    for d, m in sol["dataMappings"]:
        cpy[m] = cpy.get(m, False) or bool(inst.ds[d][2])
    full = {m for m in used_models if m not in src and m not in tgt and not cpy.get(m, False)}
    # assign[d] = (m, t) pour les datasets libres des modèles plein tarif ; les autres affectations sont figées
    win = {}      # (m, t) -> set(datasets) pour m plein tarif
    frozen = []   # paires [d, m] non concernées
    for d, m in sol["dataMappings"]:
        if m in full:
            win.setdefault((m, inst.ds[d][0]), set()).add(d)
        else:
            frozen.append([d, m])
    used_ds = {d for d, _ in sol["dataMappings"]}
    unused_free = {t: {d for d, (tt, s, c) in enumerate(inst.ds) if tt == t and not c and d not in used_ds}
                   for t in range(4)}
    energy = sum(inst.energy[m] for m in used_models)
    mono = [len(inst.reqs[m]) == 1 for m in range(nm)]
    req = {(m, t): (lb, ub) for m in range(nm) for t, lb, ub in inst.reqs[m]}
    cand_all = {t: [m for m in range(nm) if mono[m] and inst.reqs[m][0][0] == t
                    and inst.reqs[m][0][1] <= inst.reqs[m][0][2]] for t in range(4)}

    def value():
        return sum(inst.value[m] if m in full else inst.value[m] // 2 for m in used_models if m not in src)

    def solution():
        dm = list(frozen) + [[d, m] for (m, t), ds in win.items() for d in ds]
        return {"dataMappings": dm, "modelMappings": sol["modelMappings"]}

    v0 = value()
    sc, ok, msg = evaluate(k, json.dumps(solution()), inst.txt)
    assert ok and sc == v0, (sc, v0, msg)
    print(f"inst {k}: départ {v0}, créneaux plein tarif {len(win)}, libres inutilisés "
          f"{[len(unused_free[t]) for t in range(4)]}, énergie {energy / inst.cap:.6f}", flush=True)
    t0 = time.time()
    last_save = t0
    best_saved = v0
    it = gains = 0
    while time.time() - t0 < a.time:
        it += 1
        t = rng.randrange(4)
        wins_t = [w for w in win if w[1] == t]
        if not wins_t:
            continue
        mode = rng.random()
        if mode < 0.5:
            B = rng.sample(wins_t, min(a.block, len(wins_t)))
        else:  # bloc « voisin en taille » : créneaux de lb proches d'un pivot
            piv = req[rng.choice(wins_t)][0]
            B = sorted(wins_t, key=lambda w: abs(req[w][0] - piv) + rng.random() * 500)[:a.block]
        D = [d for w in B for d in win[w]]
        pool = list(unused_free[t])
        if len(pool) > 200:
            pool = rng.sample(pool, 200)
        D += pool
        sizes = {d: inst.ds[d][1] for d in D}
        totD = sum(sizes.values())
        free_e = inst.cap - energy
        cands = [m for m in cand_all[t] if (m not in used_models or (m not in full and m not in src and m not in tgt))
                 and inst.reqs[m][0][1] <= totD]
        cands = rng.sample(cands, min(a.cand, len(cands)))
        W = list(B) + [(m, t) for m in cands]
        optional = {w for w in W if mono[w[0]]}
        up = {w for w in W[len(B):] if w[0] in used_models}  # demi-tarif -> plein tarif
        gain = {w: (inst.value[w[0]] - inst.value[w[0]] // 2) if w in up else inst.value[w[0]] for w in optional}
        ecost = {w: 0 if w in up else inst.energy[w[0]] for w in optional}
        M = cp_model.CpModel()
        x = {}
        for d in D:
            for w in W:
                if sizes[d] <= req[w][1]:
                    x[d, w] = M.NewBoolVar("")
        u = {w: M.NewBoolVar("") for w in optional}
        for d in D:
            vs = [x[d, w] for w in W if (d, w) in x]
            if len(vs) > 1:
                M.AddAtMostOne(vs)
        S = {}
        for w in W:
            lb, ub = req[w]
            terms = [(sizes[d], x[d, w]) for d in D if (d, w) in x]
            S[w] = sum(c * v for c, v in terms)
            if w in optional:
                M.Add(S[w] >= lb).OnlyEnforceIf(u[w])
                M.Add(S[w] <= ub).OnlyEnforceIf(u[w])
                M.Add(S[w] == 0).OnlyEnforceIf(u[w].Not())
            else:
                M.Add(S[w] >= lb)
                M.Add(S[w] <= ub)
        # énergie : modèles mono du bloc (déjà comptés) + candidats
        e_in = sum(inst.energy[w[0]] for w in B if w in optional)
        M.Add(sum(ecost[w] * u[w] for w in optional) <= free_e + e_in)
        BIG = totD + 1
        M.Maximize(sum(BIG * gain[w] * u[w] for w in optional) - sum(S[w] for w in W))
        for w in B:
            for d in D:
                if (d, w) in x:
                    M.AddHint(x[d, w], d in win[w])
            if w in optional:
                M.AddHint(u[w], True)
        for w in W[len(B):]:
            M.AddHint(u[w], False)
            for d in D:
                if (d, w) in x:
                    M.AddHint(x[d, w], False)
        cur_obj = BIG * sum(inst.value[w[0]] for w in B if w in optional) - sum(sizes[d] for w in B for d in win[w])
        sv = cp_model.CpSolver()
        sv.parameters.max_time_in_seconds = a.sub_time
        sv.parameters.num_workers = 1
        sv.parameters.random_seed = rng.randrange(1 << 30)
        st = sv.Solve(M)
        if it <= 5 or it % 20 == 0:
            print(f"    it {it} |B|={len(B)} |D|={len(D)} |C|={len(cands)} x={len(x)} {sv.StatusName(st)} "
                  f"obj={sv.ObjectiveValue() if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None} cur={cur_obj} "
                  f"({sv.WallTime():.1f}s)", flush=True)
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE) or sv.ObjectiveValue() <= cur_obj:
            continue
        # application
        dv = 0
        for w in B:
            del win[w]
            if w in optional and not sv.Value(u[w]):
                used_models.discard(w[0]); full.discard(w[0]); energy -= inst.energy[w[0]]; dv -= inst.value[w[0]]
        for w in W:
            if w in optional and not sv.Value(u[w]):
                continue
            ds = {d for d in D if (d, w) in x and sv.Value(x[d, w])}
            win[w] = ds
            if w in up:
                frozen[:] = [p for p in frozen if p[1] != w[0]]  # ses datasets copyrightés sont libérés (perdus)
                full.add(w[0]); dv += gain[w]
            elif w[0] not in used_models:
                used_models.add(w[0]); full.add(w[0]); energy += inst.energy[w[0]]; dv += inst.value[w[0]]
        assigned = {d for w in W if w in win for d in win[w]}
        for d in D:
            if d in assigned:
                unused_free[t].discard(d)
            else:
                unused_free[t].add(d)
        assert energy <= inst.cap
        gains += 1
        if dv:
            print(f"  {time.time()-t0:.0f}s it {it} type {t}: {dv:+d} -> {value()} "
                  f"(libres inutilisés {[len(unused_free[q]) for q in range(4)]})", flush=True)
        if a.save and value() > best_saved and time.time() - last_save > a.save_every:
            txt = json.dumps(solution())
            code, sc = save_if_better(k, txt, method=f"fin_pack seed={a.seed} block={a.block}")
            last_save = time.time()
            if code == 0:
                best_saved = sc
        if it % 50 == 0:
            print(f"  {time.time()-t0:.0f}s it {it} améliorations {gains} valeur {value()}", flush=True)
    txt = json.dumps(solution())
    with open(os.path.join(ROOT, "runs", f"fin_pack_{k}_s{a.seed}.json"), "w") as f:
        f.write(txt)
    sc, ok, msg = evaluate(k, txt, inst.txt)
    print(f"fin : {sc} valide={ok} ({it} itérations)", flush=True)
    if a.save and ok and sc > best_saved:
        save_if_better(k, txt, method=f"fin_pack seed={a.seed} block={a.block}")


if __name__ == "__main__":
    main()
