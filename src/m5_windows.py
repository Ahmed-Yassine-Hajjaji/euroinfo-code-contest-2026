#!/usr/bin/env python3
"""Méthode 5 « fenêtres sur mesure » : pour les créneaux à fort excès, remplacer le modèle occupant (générateur, ou
modèle entraîné mono-besoin) par un modèle libre du même type dont la fenêtre [lb, ub] contient un SOUS-PAQUET du
paquet en place (0, 1 ou 2 datasets retirés -> libérés pour le LNS), et/ou moins gourmand en énergie.
Choix couplé par un petit MIP (highspy) : un remplacement max par créneau, un modèle candidat utilisé une fois,
énergie totale <= cap, objectif = valeur des datasets libérés aux prix duaux LP + énergie libérée au prix dual + Δvaleur.

Usage : python src/m5_windows.py <k> <sol_in> <sol_out> [--emin 200] [--drop 2] [--K 40] [--lam-e 1] [--time 60]
        [--seed 0] [--noise 0] [--all-slots]
Sortie : solution valide (score >= entrée) ; affiche remplacements, unités et énergie libérées.
"""
import argparse
import json
import os
import random
import sys
import time
from itertools import combinations

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402
from m3_prep import slots_of  # noqa: E402
from save_if_better import evaluate  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("k", type=int)
    ap.add_argument("sol_in")
    ap.add_argument("sol_out")
    ap.add_argument("--emin", type=int, default=200, help="excès minimal d'un créneau candidat")
    ap.add_argument("--drop", type=int, default=2, help="datasets retirés max par créneau")
    ap.add_argument("--K", type=int, default=40, help="options gardées par créneau")
    ap.add_argument("--lam-e", type=float, default=1.0, help="poids de l'énergie libérée (× prix dual)")
    ap.add_argument("--time", type=float, default=60)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--noise", type=float, default=0.0, help="bruit multiplicatif sur les gains (diversité)")
    ap.add_argument("--all-slots", action="store_true", help="tous les créneaux, pas seulement excès >= emin")
    ap.add_argument("--no-trained", action="store_true", help="générateurs seulement")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    t0 = time.time()
    inst = Instance(a.k)
    sol = json.load(open(a.sol_in))
    lp = json.load(open(os.path.join(ROOT, "runs", f"lp_{a.k}.json")))
    wfree = [lp["dual_free"][t] + lp["dual_total"][t] for t in range(4)]
    wcopy = [lp["dual_total"][t] for t in range(4)]
    pe = lp["dual_energy"] / inst.cap  # prix dual d'une unité d'énergie
    nm = len(inst.value)
    slots, assign = slots_of(inst, sol)
    src = {s: t for s, t in sol["modelMappings"]}
    used = [0] * nm
    for m in {m for _, m in sol["dataMappings"]} | set(src.values()):
        used[m] = 1
    for g in src:
        used[g] = 2
    E = sum(inst.energy[m] for m in range(nm) if used[m])
    nslot = len(slots)
    packs = [[] for _ in range(nslot)]
    for d, s in enumerate(assign):
        if s >= 0:
            packs[s].append(d)
    # nombre de créneaux (besoins de données) par modèle entraîné : on ne remplace que les mono-créneau
    nslots_of = {}
    for t, lb, ub, fo, m in slots:
        nslots_of[m] = nslots_of.get(m, 0) + 1
    # candidats libres par type : (lb, ub, e, v, m)
    cand = [[] for _ in range(4)]
    for m in range(nm):
        if used[m] == 0 and inst.gen_ok[m]:
            t, lb, ub = inst.reqs[m][0]
            cand[t].append((lb, ub, inst.energy[m], inst.value[m], m))
    for t in range(4):
        cand[t].sort()
    options = []  # (gain, slot, m_new, dropped tuple, e_new - e_old, dvalue)
    nhigh = 0
    for s, (t, lb, ub, fo, m) in enumerate(slots):
        P = packs[s]
        S = sum(inst.ds[d][1] for d in P)
        exc = S - lb
        if not a.all_slots and exc < a.emin:
            continue
        is_gen = used[m] == 2
        if not is_gen:
            if a.no_trained or len(inst.reqs[m]) != 1 or nslots_of.get(m, 0) != 1:
                continue
        nhigh += 1
        e_old = inst.energy[m]
        if is_gen:
            v_old = 0
        else:
            half = any(inst.ds[d][2] for d in P)
            v_old = inst.value[m] // 2 if half else inst.value[m]
        subs = [()]
        Ps = sorted(P, key=lambda d: -inst.ds[d][1])[:12]
        for r in range(1, min(a.drop, len(P) - 1) + 1):
            subs.extend(combinations(Ps, r))
        local = []
        for D in subs:
            S2 = S - sum(inst.ds[d][1] for d in D)
            freed = sum((wfree if not inst.ds[d][2] else wcopy)[inst.ds[d][0]] * inst.ds[d][1] for d in D)
            Dset = set(D)
            half = any(inst.ds[d][2] for d in P if d not in Dset)
            for lb2, ub2, e2, v2, m2 in cand[t]:
                if lb2 > S2:
                    break
                if ub2 < S2:
                    continue
                if is_gen:
                    dv = 0
                else:
                    v_new = v2 // 2 if half else v2
                    dv = v_new - v_old
                    if dv < 0:
                        continue
                gain = freed + a.lam_e * pe * (e_old - e2) + dv
                if gain <= 1e-9:
                    continue
                if a.noise > 0:
                    gain *= 1 + a.noise * rng.random()
                local.append((gain, s, m2, D, e2 - e_old, dv))
        local.sort(key=lambda x: -x[0])
        options.extend(local[: a.K])
    print(f"m5: {nhigh} créneaux candidats (excès >= {a.emin}), {len(options)} options, énergie {E}/{inst.cap} "
          f"({E / inst.cap:.4f}), {time.time() - t0:.1f}s", flush=True)
    if not options:
        with open(a.sol_out, "w") as f:
            json.dump(sol, f)
        print("m5: aucune option ; solution recopiée")
        return 1
    # MIP highspy
    import highspy
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("time_limit", float(a.time))
    h.setOptionValue("threads", 1)
    h.setOptionValue("mip_rel_gap", 1e-6)
    n = len(options)
    inf = highspy.kHighsInf
    for gain, *_ in options:
        h.addVar(0.0, 1.0)
    h.changeColsCost(n, list(range(n)), [-g for g, *_ in options])
    h.changeColsIntegrality(n, list(range(n)), [highspy.HighsVarType.kInteger] * n)
    by_slot, by_model = {}, {}
    for i, (_, s, m2, D, de, dv) in enumerate(options):
        by_slot.setdefault(s, []).append(i)
        by_model.setdefault(m2, []).append(i)
    for idx in list(by_slot.values()) + list(by_model.values()):
        if len(idx) > 1:
            h.addRow(-inf, 1.0, len(idx), idx, [1.0] * len(idx))
    h.addRow(-inf, float(inst.cap - E), n, list(range(n)), [float(o[4]) for o in options])
    h.run()
    x = h.getSolution().col_value
    chosen = [options[i] for i in range(n) if x[i] > 0.5]
    # application
    mm = [list(p) for p in sol["modelMappings"]]
    dm = [list(p) for p in sol["dataMappings"]]
    remap, dropped = {}, set()
    freed_u = de_tot = dv_tot = 0
    for gain, s, m2, D, de, dv in chosen:
        m = slots[s][4]
        remap[m] = m2
        dropped |= set(D)
        freed_u += sum(inst.ds[d][1] for d in D)
        de_tot += de
        dv_tot += dv
    for p in mm:
        if p[0] in remap:
            p[0] = remap[p[0]]
    dm2 = []
    for d, m in dm:
        if d in dropped:
            continue
        dm2.append([d, remap.get(m, m)])
    new = {"dataMappings": dm2, "modelMappings": mm}
    txt = json.dumps(new)
    score, ok, msg = evaluate(a.k, txt)
    ref = evaluate(a.k, json.dumps(sol))[0]
    ngen = sum(1 for _, s, *_ in chosen if used[slots[s][4]] == 2)
    print(f"m5: {len(chosen)} remplacements ({ngen} générateurs), datasets libérés {len(dropped)} = {freed_u} u., "
          f"énergie {de_tot:+d} ({(E + de_tot) / inst.cap:.4f}), Δvaleur {dv_tot:+d} ; score {score} (réf {ref}) "
          f"valide={ok} {'' if ok else msg} ; {time.time() - t0:.1f}s", flush=True)
    if not ok or score < ref:
        print("m5: solution rejetée, recopie de l'entrée")
        new = sol
    with open(a.sol_out, "w") as f:
        json.dump(new, f)
    return 0 if (ok and score >= ref and chosen) else 1


if __name__ == "__main__":
    sys.exit(main())
