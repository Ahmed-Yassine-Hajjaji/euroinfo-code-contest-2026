#!/usr/bin/env python3
"""m8 : tabou m3 restreinte à UN type de données (4x plus d'itérations sur le type visé), avec λ/mu libres, puis
reconstruction et bascules (m8_apply). Le .in restreint est dérivé de m3_prep.slots_of (aucun fichier existant modifié).
Usage : python src/m8_tabu.py <k> <sol.json> <type 0-3> <seed> <time_s> [--lam 1e-7] [--mu 1] [--tenure 50] [--ncand 16]
        [--pert 30] [--stagn 2000000] [--tag x] [--save]
Sortie : runs/m8_<tag>_tab.json (solution reconstruite), ligne 'm8_tabu: ... libres=[...]'.
"""
import argparse, json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from greedy import Instance
from m3_prep import slots_of
from save_if_better import evaluate, save_if_better
import m8_apply

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "src", "m3_tabu", "target", "release", "m3_tabu")
TN = "ntic"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("k", type=int); ap.add_argument("sol"); ap.add_argument("type", type=int); ap.add_argument("seed", type=int)
    ap.add_argument("time", type=float); ap.add_argument("--lam", default="1e-7"); ap.add_argument("--mu", default="1")
    ap.add_argument("--tenure", type=int, default=50); ap.add_argument("--ncand", type=int, default=16)
    ap.add_argument("--pert", type=int, default=30); ap.add_argument("--stagn", type=int, default=2000000)
    ap.add_argument("--tag", default="x"); ap.add_argument("--save", action="store_true")
    ap.add_argument("--wfree", type=int, default=0, help="poids libre forcé (unités 1e-6), 0 = duaux LP")
    a = ap.parse_args()
    k, T = a.k, a.type
    inst = Instance(k)
    sol = json.load(open(a.sol))
    slots, assign = slots_of(inst, sol)
    lp = json.load(open(os.path.join(ROOT, "runs", f"lp_{k}.json")))
    wf = [int(round((lp["dual_free"][t] + lp["dual_total"][t]) * 1e6)) for t in range(4)]
    wc = [int(round(lp["dual_total"][t] * 1e6)) for t in range(4)]
    if a.wfree:
        wf = [a.wfree] * 4
    # restriction au type T
    sidx = [i for i, s in enumerate(slots) if s[0] == T]
    smap = {i: j for j, i in enumerate(sidx)}
    didx = [d for d, (t, _, _) in enumerate(inst.ds) if t == T]
    fin = os.path.join(ROOT, "runs", f"m8_{a.tag}.in"); fout = os.path.join(ROOT, "runs", f"m8_{a.tag}.out")
    with open(fin, "w") as f:
        f.write(f"{len(didx)} {len(sidx)}\n")
        f.write(" ".join(map(str, wf + wc)) + "\n")
        for d in didx:
            t, s, c = inst.ds[d]
            f.write(f"{t} {s} {0 if c else 1} {smap[assign[d]] if assign[d] >= 0 else -1}\n")
        for i in sidx:
            t, lb, ub, fo, m = slots[i]
            f.write(f"{t} {lb} {ub} {fo} {m}\n")
    cmd = [BIN, fin, fout, str(a.seed), str(a.time), str(a.tenure), a.lam, str(a.ncand), str(a.stagn), str(a.pert), a.mu]
    log = os.path.join(ROOT, "logs", f"m8_{a.tag}_tabu.log")
    with open(log, "w") as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=a.time + 120)
    tb = [l for l in open(log).read().splitlines() if "best gasp" in l]
    out = [int(x) for x in open(fout).read().split()]
    assert len(out) == len(didx)
    new_assign = list(assign)
    for d, j in zip(didx, out):
        new_assign[d] = sidx[j] if j >= 0 and j < len(sidx) else -1
    dm = [[d, slots[s][4]] for d, s in enumerate(new_assign) if s >= 0]
    new = {"dataMappings": dm, "modelMappings": sol["modelMappings"]}
    txt = json.dumps(new)
    sc, ok, msg = evaluate(k, txt, inst.txt)
    s0 = evaluate(k, json.dumps(sol), inst.txt)[0]
    free = sorted((inst.ds[d][1], 'C' if inst.ds[d][2] else 'L') for d, s in enumerate(new_assign) if s < 0)
    waste = sum(inst.ds[d][1] for d, s in enumerate(new_assign) if s >= 0) - sum(lb for _, lb, _, _, _ in slots)
    outp = os.path.join(ROOT, "runs", f"m8_{a.tag}_tab.json")
    if ok and sc >= s0:
        open(outp, "w").write(txt)
    print(f"m8_tabu type {TN[T]} seed {a.seed} lam {a.lam} mu {a.mu} : {s0} -> {sc} valide={ok} {msg if not ok else ''} "
          f"gaspillage {waste} libres={free} | {tb[-1].split('|')[-1].strip()[:60] if tb else '?'}", flush=True)
    if ok and sc >= s0:
        new2, gain, desc = m8_apply.search(inst, new, quiet=True)
        if gain > 0:
            txt2 = json.dumps(new2); sc2, ok2, _ = evaluate(k, txt2, inst.txt)
            print(f"  bascule : {sc} -> {sc2} valide={ok2} : {desc}", flush=True)
            if ok2 and sc2 > sc:
                open(outp.replace("_tab.json", "_bas.json"), "w").write(txt2)
                if a.save:
                    save_if_better(k, txt2, method=f"m8 tabu type{T} seed{a.seed} lam{a.lam} mu{a.mu} + {desc[:60]}", dataset_txt=inst.txt)

if __name__ == "__main__":
    main()
