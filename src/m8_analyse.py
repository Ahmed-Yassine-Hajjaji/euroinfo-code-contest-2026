#!/usr/bin/env python3
"""m8 : analyse des bascules de tarif possibles sur une solution (instance 6 par défaut).
Classe les modèles entraînés : f (plein tarif), hc (demi-tarif à cause du copyright, sans générateur), z (cible de
générateur), y (générateur). Pour chaque bascule candidate calcule le gain et le BESOIN en datasets libres.
Usage : python src/m8_analyse.py <k> [sol.json] [--top 20]
"""
import argparse, json, os, sys
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from greedy import Instance

TN = "ntic"

def classify(inst, sol):
    src = {s: t for s, t in sol["modelMappings"]}
    cov = defaultdict(list)
    for s, t in sol["modelMappings"]:
        cov[t].append(s)
    byd = defaultdict(list)
    for d, m in sol["dataMappings"]:
        byd[m].append(d)
    trained = (set(byd) | set(cov)) - set(src)
    cls = {}
    for m in trained:
        cp = any(inst.ds[d][2] for d in byd[m])
        if m in cov:
            cls[m] = "z"
        elif cp:
            cls[m] = "hc"
        else:
            cls[m] = "f"
    for g in src:
        cls[g] = "y"
    return cls, byd, src, cov

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("k", type=int); ap.add_argument("sol", nargs="?", default=None); ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()
    k = a.k; inst = Instance(k)
    sol = json.load(open(a.sol or f"best/instance_{k}.json"))
    cls, byd, src, cov = classify(inst, sol)
    cnt = Counter(cls.values())
    E = sum(inst.energy[m] for m in cls)
    print(f"classes {dict(cnt)} ; énergie reste {inst.cap - E:.3e} / {inst.cap:.3e}")
    used = {d for d, _ in sol["dataMappings"]}
    free_unused = [d for d in range(len(inst.ds)) if d not in used]
    print(f"datasets non utilisés : {[(d, TN[inst.ds[d][0]], inst.ds[d][1], 'C' if inst.ds[d][2] else 'L') for d in free_unused]}")
    # offre libre par type, consommation lb des f, gaspillage par type (f seulement et total)
    F = [0]*4; C = [0]*4
    for t, s, c in inst.ds:
        (C if c else F)[t] += s
    wf = [0]*4; wt = [0]*4; nf = [0]*4
    for m, ds in byd.items():
        if m in src: 
            lb = inst.reqs[m][0][1]; wt[inst.reqs[m][0][0]] += sum(inst.ds[d][1] for d in ds) - lb; continue
        fill = Counter()
        for d in ds: fill[inst.ds[d][0]] += inst.ds[d][1]
        for t, v in fill.items():
            if t in {inst.reqs[g][0][0] for g in cov.get(m, [])}:
                wt[t] += v; continue
            lb = next(lb for tt, lb, _ in inst.reqs[m] if tt == t)
            wt[t] += v - lb
            if cls[m] == "f": wf[t] += v - lb; nf[t] += 1
    print("type | offre libre | offre copyright | gaspillage créneaux f | nb créneaux f | gaspillage total")
    for t in range(4):
        print(f"  {TN[t]} | {F[t]} | {C[t]} | {wf[t]} | {nf[t]} | {wt[t]}")
    print(f"gaspillage total {sum(wt)} dont f {sum(wf)}")
    # --- bascules ---
    rows = []
    # (A) hc -> f : remplacer les datasets copyrightés par des libres, par type
    for m, c in cls.items():
        if c != "hc": continue
        need = []
        for t, lb, ub in inst.reqs[m]:
            ds = [d for d in byd[m] if inst.ds[d][0] == t]
            fr = sum(inst.ds[d][1] for d in ds if not inst.ds[d][2]); cp = [inst.ds[d][1] for d in ds if inst.ds[d][2]]
            if cp:
                need.append((t, lb - fr, ub - fr, sorted(cp)))
        gain = inst.value[m] - inst.value[m] // 2
        rows.append((gain, "hc->f", m, inst.value[m], 0, need, f"copyright libérés {[(TN[t], cp) for t,_,_,cp in need]}"))
    # (B) z -> f : retirer le générateur, remplir la cible avec du libre ; énergie libérée E_g, datasets de g libérés
    for m, c in cls.items():
        if c != "z": continue
        gs = cov[m]
        if len(gs) != 1 or len(inst.reqs[m]) != 1: continue  # cibles multi : à traiter séparément
        t, lb, ub = inst.reqs[m][0]
        if lb > ub: continue
        g = gs[0]
        gds = byd[g]
        gain = inst.value[m] - inst.value[m] // 2
        rows.append((gain, "z->f", m, inst.value[m], inst.energy[g], [(t, lb, ub, [])],
                     f"gén {g} retiré : énergie {inst.energy[g]:.2e}, libère {[(TN[inst.ds[d][0]], inst.ds[d][1], 'C' if inst.ds[d][2] else 'L') for d in gds]}"))
    rows.sort(key=lambda r: -r[0])
    print(f"\n{len([r for r in rows if r[1]=='hc->f'])} bascules hc->f, {len([r for r in rows if r[1]=='z->f'])} bascules z->f (cibles mono, 1 gén)")
    print("gain | type | modèle | valeur | énergie libérée | besoin libre [lb-fr, ub-fr] par type | détail")
    for r in rows[:a.top]:
        gain, kind, m, v, e, need, det = r
        nd = "; ".join(f"{TN[t]}:[{lo},{hi}]" for t, lo, hi, _ in need)
        print(f"{gain} | {kind} | {m} | {v} | {e:.2e} | {nd} | {det}")
    # (C) f -> h candidates : smallest loss, free datasets released
    fh = []
    for m, c in cls.items():
        if c != "f": continue
        loss = inst.value[m] - inst.value[m] // 2
        rel = [(TN[inst.ds[d][0]], inst.ds[d][1]) for d in byd[m]]
        fh.append((loss, m, inst.value[m], rel, [(TN[t], lb, ub) for t, lb, ub in inst.reqs[m]]))
    fh.sort()
    print(f"\n{len(fh)} modèles f ; les 15 bascules f->h les moins coûteuses (perte | modèle | valeur | datasets libres libérés | fenêtres à remplir en copyright) :")
    for r in fh[:15]:
        print(" ", r)
    # distribution des tailles libres / copyright par type
    for t in range(4):
        fr = sorted(s for tt, s, c in inst.ds if tt == t and not c)
        cp = sorted(s for tt, s, c in inst.ds if tt == t and c)
        print(f"type {TN[t]}: {len(fr)} libres (min {fr[0]}, méd {fr[len(fr)//2]}, max {fr[-1]}), {len(cp)} copyright (min {cp[0]}, méd {cp[len(cp)//2]})")
    json.dump({"rows": [(r[0], r[1], r[2], r[3], r[4], [(t, lo, hi) for t, lo, hi, _ in r[5]]) for r in rows]}, open("runs/m8/bascules.json", "w"))

if __name__ == "__main__":
    main()
