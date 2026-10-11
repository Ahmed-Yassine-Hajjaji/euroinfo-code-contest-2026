#!/usr/bin/env python3
"""Réalisation exacte par blocs (CP-SAT) de rôles agrégés : rôles (f,h,y,z) fixés par le MIP agrégé « offre
effective », affectation datasets -> créneaux par type et par blocs de N créneaux, solution courante en hint,
abandons pénalisés (poids = part de valeur du modèle). Puis assemblage (appariement générateurs/cibles par comptage),
validation officielle, save_if_better.

Usage : python src/realize_cp.py <k> <rôles.json> [--start sol.json] [--block 350] [--time 60] [--workers 4]
        [--pool 400] [--seed 0] [--out runs/x.json] [--save] [--passes 1]
"""
import argparse
import json
import os
import random
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402
from cp_pack import pack  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("roles")
    ap.add_argument("--start", default=None, help="solution de départ (hint), défaut best/")
    ap.add_argument("--block", type=int, default=350)
    ap.add_argument("--time", type=float, default=60.0, help="secondes CP-SAT par bloc")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--pool", type=int, default=400, help="datasets non affectés max ajoutés à un bloc")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--passes", type=int, default=1)
    ap.add_argument("--eps", type=float, default=0.005, help="points par unité de donnée consommée (prix dual ≈ 0,005)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    inst = Instance(a.instance)
    nm = len(inst.value)
    ro = json.load(open(a.roles))
    start = a.start or os.path.join(ROOT, "best", f"instance_{a.instance}.json")
    sol = json.load(open(start))
    t0 = time.time()
    # ---- créneaux issus des rôles ----
    slots = {}  # sid -> (t, lb, ub, w, allow_cr, kind, owner)
    zneed = Counter()
    for m in range(nm):
        rq = inst.reqs[m]
        if ro["f"][m] > 0.5:
            for t, lb, ub in rq:
                slots[(m, t)] = (t, lb, ub, inst.value[m] / len(rq), False, "F", m)
        elif ro["h"][m] > 0.5:
            for t, lb, ub in rq:
                if t in ro["z"][m]:
                    zneed[t] += 1
                else:
                    slots[(m, t)] = (t, lb, ub, (inst.value[m] // 2) / len(rq), True, "H", m)
    # poids d'un générateur de type t = demi-valeur moyenne apportée par une couverture de type t
    zval = Counter()
    for m in range(nm):
        if ro["h"][m] > 0.5:
            for t in ro["z"][m]:
                zval[t] += (inst.value[m] // 2) / len(inst.reqs[m])
    nY = Counter(inst.reqs[g][0][0] for g in range(nm) if ro["y"][g] > 0.5)
    for g in range(nm):
        if ro["y"][g] > 0.5:
            t, lb, ub = inst.reqs[g][0]
            slots[("g", g)] = (t, lb, ub, zval[t] / max(nY[t], 1), True, "Y", g)
    # ---- hint depuis la solution de départ ----
    src = {s for s, _ in sol["modelMappings"]}
    hint = {}
    for d, m in sol["dataMappings"]:
        sid = ("g", m) if m in src else (m, inst.ds[d][0])
        if sid in slots:
            hint.setdefault(sid, []).append(d)
    print(f"inst {a.instance} rôles {a.roles} : {len(slots)} créneaux (F {sum(1 for s in slots.values() if s[5]=='F')}, "
          f"H {sum(1 for s in slots.values() if s[5]=='H')}, Y {sum(1 for s in slots.values() if s[5]=='Y')}), "
          f"hint pour {len(hint)} créneaux depuis {start}", flush=True)
    assign = dict(hint)  # sid -> datasets (état courant, mis à jour bloc par bloc)
    active = {sid: bool(assign.get(sid)) for sid in slots}
    for p in range(a.passes):
        for t in range(4):
            sids = [sid for sid, s in slots.items() if s[0] == t]
            rng.shuffle(sids)
            used = {d for sid in sids for d in assign.get(sid, [])}
            pool = [d for d, (tt, _, _) in enumerate(inst.ds) if tt == t and d not in used]
            nb = max(1, (len(sids) + a.block - 1) // a.block)
            for b in range(nb):
                bs = sids[b * len(sids) // nb:(b + 1) * len(sids) // nb]
                ds_ids = {d for sid in bs for d in assign.get(sid, [])}
                extra = pool if len(pool) <= a.pool else rng.sample(pool, a.pool)
                ds_ids |= set(extra)
                datasets = [(d, inst.ds[d][1], inst.ds[d][2]) for d in sorted(ds_ids)]
                # poids : valeur entière du modèle si tous ses autres créneaux sont actifs (le perdre coûte tout),
                # sinon sa part (valeur / nb de besoins)
                sl = []
                for sid in bs:
                    t_, lb, ub, w, cr, kind, owner = slots[sid]
                    if kind in ("F", "H"):
                        others = [(owner, tt) for tt, _, _ in inst.reqs[owner] if (owner, tt) in slots and (owner, tt) != sid]
                        if others and all(active.get(o) for o in others):
                            w = inst.value[owner] if kind == "F" else inst.value[owner] // 2
                    sl.append((sid, lb, ub, w, cr))
                h = {sid: assign.get(sid, []) for sid in bs}
                res, act, status, obj = pack(datasets, sl, tlimit=a.time, workers=a.workers, hint=h, eps=a.eps)
                if res is None:
                    print(f"  type {t} bloc {b}: échec {status}", flush=True); continue
                before = sum(1 for sid in bs if active[sid]); wb = sum(sum(inst.ds[d][1] for d in assign.get(sid, [])) - slots[sid][1] for sid in bs if active[sid])
                for sid in bs:
                    assign[sid] = res[sid] if act[sid] else []
                    active[sid] = act[sid]
                after = sum(1 for sid in bs if active[sid]); wa = sum(sum(inst.ds[d][1] for d in assign[sid]) - slots[sid][1] for sid in bs if active[sid])
                used_b = {d for sid in bs for d in assign[sid]}
                pool = [d for d in pool if d not in used_b] + [d for d in ds_ids if d not in used_b and d not in pool]
                print(f"  passe {p+1} type {'ntic'[t]} bloc {b+1}/{nb}: {len(bs)} créneaux, {len(datasets)} datasets, actifs {before}->{after}, "
                      f"gaspillage {wb}->{wa}, {status} ({obj[2]:.0f}s), pool {len(pool)}", flush=True)
    # ---- assemblage ----
    trained = set()
    for m in range(nm):
        if ro["f"][m] > 0.5 or ro["h"][m] > 0.5:
            if all(active.get((m, t), False) for t, _, _ in inst.reqs[m] if (m, t) in slots):
                trained.add(m)
    gens_act = {t: [g for g in range(nm) if ro["y"][g] > 0.5 and active.get(("g", g)) and inst.reqs[g][0][0] == t] for t in range(4)}
    # cibles : besoins z ; si pas assez de générateurs, on retire les cibles de moindre valeur
    targets = {t: sorted([m for m in trained if ro["h"][m] > 0.5 and t in ro["z"][m]], key=lambda m: -inst.value[m]) for t in range(4)}
    dropped = 0
    changed = True
    while changed:
        changed = False
        for t in range(4):
            while len(targets[t]) > len(gens_act[t]):
                m = targets[t].pop(); trained.discard(m); dropped += 1; changed = True
                for tt in range(4):
                    if m in targets[tt]:
                        targets[tt].remove(m)
    dm, mm = [], []
    for m in trained:
        for t, _, _ in inst.reqs[m]:
            if (m, t) in slots:
                dm.extend([d, m] for d in assign[(m, t)])
    for t in range(4):
        for g, m in zip(gens_act[t], targets[t]):
            mm.append([g, m]); dm.extend([d, g] for d in assign[("g", g)])
    out_sol = {"dataMappings": [[int(d), int(m)] for d, m in dm], "modelMappings": [[int(g), int(m)] for g, m in mm]}
    txt = json.dumps(out_sol, separators=(",", ":"))
    from save_if_better import evaluate, save_if_better
    sc, ok, msg = evaluate(a.instance, txt, inst.txt)
    E = sum(inst.energy[m] for m in trained) + sum(inst.energy[g] for t in range(4) for g in gens_act[t][:len(targets[t])])
    print(f"  assemblage : {len(trained)} modèles, {len(mm)} générateurs utilisés / {sum(len(v) for v in gens_act.values())} actifs, "
          f"{dropped} cibles retirées, énergie {E/inst.cap:.4f} ; score officiel {sc} valide={ok} {msg} ({time.time()-t0:.0f}s)", flush=True)
    out = a.out or os.path.join(ROOT, "runs", f"realize_cp_{a.instance}.json")
    with open(out, "w") as f:
        f.write(txt)
    if a.save and ok:
        save_if_better(a.instance, txt, method=f"realize_cp {os.path.basename(a.roles)} block={a.block} t={a.time:.0f}", dataset_txt=inst.txt)


if __name__ == "__main__":
    main()
