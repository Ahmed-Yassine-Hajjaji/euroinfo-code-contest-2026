#!/usr/bin/env python3
"""m8 : applique des bascules de tarif à une solution en utilisant ses datasets NON UTILISÉS.
  - hc -> f : modèle demi-tarif (copyright, sans générateur) : ses datasets copyrightés sont retirés et remplacés par
    des datasets libres inutilisés (subset-sum exact dans [lb - libre_déjà_présent, ub - ...]) ; gain v - v//2.
  - paire (f -> h) + (hc -> f) : un modèle f de faible valeur est rempli avec des datasets copyrightés inutilisés
    (dont ceux libérés par la bascule), ses datasets libres rejoignent le pool, puis hc -> f ; gain net > 0 exigé.
Usage : python src/m8_apply.py <k> <sol.json> [--out out.json] [--save] [--method "m8 ..."] [--quiet]
Sortie : score avant/après ; code 0 si amélioré, 1 sinon.
"""
import argparse, itertools, json, os, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from greedy import Instance
from save_if_better import evaluate, save_if_better
from m8_analyse import classify

TN = "ntic"

def subset_in(items, lo, hi):
    """items: liste (taille, id). Retourne un sous-ensemble de somme dans [lo, hi] (somme minimale), ou None."""
    lo = max(lo, 0)
    if lo == 0 and hi >= 0:
        return []
    if hi < lo:
        return None
    items = sorted(items)
    # DP exacte (sommes <= hi) : bitset -> tailles raisonnables (pool petit)
    reach = {0: []}
    for s, i in items:
        new = {}
        for tot, sel in reach.items():
            t2 = tot + s
            if t2 <= hi and t2 not in reach and t2 not in new:
                new[t2] = sel + [i]
        reach.update(new)
        if len(reach) > 200000:
            break
    best = None
    for tot, sel in reach.items():
        if lo <= tot <= hi and (best is None or tot < best[0]):
            best = (tot, sel)
    return best[1] if best else None

def state_of(inst, sol):
    cls, byd, src, cov = classify(inst, sol)
    used = {d for d, _ in sol["dataMappings"]}
    pool_f = defaultdict(list); pool_c = defaultdict(list)
    for d, (t, s, c) in enumerate(inst.ds):
        if d not in used:
            (pool_c if c else pool_f)[t].append((s, d))
    return cls, byd, src, cov, pool_f, pool_c

def try_hc_to_f(inst, m, byd, pool_f):
    """Retourne (datasets retirés (copyright), datasets ajoutés (libres)) ou None."""
    rem, add = [], []
    pf = {t: list(v) for t, v in pool_f.items()}
    for t, lb, ub in inst.reqs[m]:
        ds = [d for d in byd[m] if inst.ds[d][0] == t]
        cp = [d for d in ds if inst.ds[d][2]]
        if not cp:
            continue
        fr = sum(inst.ds[d][1] for d in ds if not inst.ds[d][2])
        sel = subset_in(pf.get(t, []), lb - fr, ub - fr)
        if sel is None:
            return None
        rem += cp; add += sel
        pf[t] = [(s, d) for s, d in pf[t] if d not in sel]
    return rem, add

def f_to_h_options(inst, M, byd, pool_c, t):
    """Pour le type t de M : sélections (copyrightés du pool + libres propres) de somme dans [lb, ub] contenant au moins
    un copyrighté. Retourne liste de (libres retirés, copyrightés ajoutés), triée par taille libérée décroissante."""
    lb, ub = next((lb, ub) for tt, lb, ub in inst.reqs[M] if tt == t)
    own = [(inst.ds[d][1], d) for d in byd[M] if inst.ds[d][0] == t]
    cp = list(pool_c.get(t, []))
    if not cp:
        return []
    items = [(s, d, 1) for s, d in cp] + [(s, d, 0) for s, d in own]
    if len(items) > 16:
        items = sorted(items, key=lambda x: -x[2])[:16]
    res = []
    n = len(items)
    for mask in range(1, 1 << n):
        tot = 0; ncp = 0
        for i in range(n):
            if mask >> i & 1:
                tot += items[i][0]; ncp += items[i][2]
        if ncp and lb <= tot <= ub:
            sel = [items[i][1] for i in range(n) if mask >> i & 1]
            rem = [d for s, d in own if d not in sel]
            add = [d for d in sel if d in {dd for _, dd in cp}]
            res.append((sum(inst.ds[d][1] for d in rem), rem, add))
    res.sort(key=lambda x: -x[0])
    return [(r, a) for _, r, a in res[:30]]

def apply_moves(sol, moves):
    """moves: liste de (modèle, retirés, ajoutés)."""
    dm = [list(x) for x in sol["dataMappings"]]
    for m, rem, add in moves:
        rs = set(rem)
        dm = [x for x in dm if not (x[1] == m and x[0] in rs)]
        dm += [[d, m] for d in add]
    return {"dataMappings": dm, "modelMappings": sol["modelMappings"]}

def search(inst, sol, quiet=False):
    """Retourne (meilleure solution, gain, description)."""
    cls, byd, src, cov, pool_f, pool_c = state_of(inst, sol)
    hcs = [m for m, c in cls.items() if c == "hc"]
    pf_desc = {TN[t]: sorted(s for s, _ in v) for t, v in pool_f.items()}
    pc_desc = {TN[t]: sorted(s for s, _ in v) for t, v in pool_c.items()}
    if not quiet:
        print(f"hc {[(m, inst.value[m]) for m in hcs]} ; pool libre {pf_desc} ; pool copyright {pc_desc}")
    best = (0, None, "")
    # 1) hc -> f direct (toutes combinaisons séquentielles)
    for order in itertools.permutations(hcs):
        pf = {t: list(v) for t, v in pool_f.items()}
        moves, gain, desc = [], 0, []
        for m in order:
            r = try_hc_to_f(inst, m, byd, pf)
            if r is None:
                continue
            rem, add = r
            moves.append((m, rem, add)); gain += inst.value[m] - inst.value[m] // 2
            desc.append(f"hc->f {m} (+{inst.value[m] - inst.value[m] // 2}) libres {[inst.ds[d][1] for d in add]}")
            for d in add:
                t = inst.ds[d][0]; pf[t] = [(s, dd) for s, dd in pf[t] if dd != d]
        if gain > best[0]:
            best = (gain, moves, " ; ".join(desc))
    # 2) paire(s) f -> h (un type modifié par modèle f, jusqu'à 2 modèles) puis hc -> f
    fs = sorted((inst.value[M] - inst.value[M] // 2, M) for M, c in cls.items() if c == "f")
    for m in hcs:
        g = inst.value[m] - inst.value[m] // 2
        need_t = {t for t, lb, ub in inst.reqs[m] if any(inst.ds[d][2] for d in byd[m] if inst.ds[d][0] == t)}
        pc0 = {t: list(pool_c.get(t, [])) for t in range(4)}
        for d in byd[m]:
            if inst.ds[d][2]:
                pc0[inst.ds[d][0]].append((inst.ds[d][1], d))
        cands = []  # (loss, M, t, rem, add)
        for loss, M in fs:
            if loss >= g:
                break
            for t in need_t:
                if not any(tt == t for tt, _, _ in inst.reqs[M]):
                    continue
                for rem, add in f_to_h_options(inst, M, byd, pc0, t):
                    cands.append((loss, M, t, rem, add))
        def test(sel_cands):
            pf = {t: list(pool_f.get(t, [])) for t in range(4)}
            used_cp = set()
            for loss, M, t, rem, add in sel_cands:
                if used_cp & set(add):
                    return None
                used_cp |= set(add)
                for d in rem:
                    pf[inst.ds[d][0]].append((inst.ds[d][1], d))
            return try_hc_to_f(inst, m, byd, pf)
        for c1 in cands:
            loss = c1[0]
            if g - loss <= best[0]:
                continue
            r2 = test([c1])
            if r2 is not None:
                best = (g - loss, [(m, r2[0], r2[1]), (c1[1], c1[3], c1[4])],
                        f"f->h {c1[1]} (-{loss}) copyright {[inst.ds[d][1] for d in c1[4]]} ; hc->f {m} (+{g}) libres {[inst.ds[d][1] for d in r2[1]]}")
        # paires de deux modèles f
        cands2 = [c for c in cands if c[0] < g - 1]
        cands2 = cands2[:60]
        for i in range(len(cands2)):
            for j in range(i + 1, len(cands2)):
                c1, c2 = cands2[i], cands2[j]
                if c1[1] == c2[1]:
                    continue
                loss = c1[0] + c2[0]
                if g - loss <= best[0]:
                    continue
                r2 = test([c1, c2])
                if r2 is not None:
                    best = (g - loss, [(m, r2[0], r2[1]), (c1[1], c1[3], c1[4]), (c2[1], c2[3], c2[4])],
                            f"f->h {c1[1]} (-{c1[0]}) + f->h {c2[1]} (-{c2[0]}) ; hc->f {m} (+{g}) libres {[inst.ds[d][1] for d in r2[1]]}")
    if best[1] is None:
        return sol, 0, "aucune bascule"
    return apply_moves(sol, best[1]), best[0], best[2]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("k", type=int); ap.add_argument("sol"); ap.add_argument("--out", default=None)
    ap.add_argument("--save", action="store_true"); ap.add_argument("--method", default="m8 apply"); ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    inst = Instance(a.k)
    sol = json.load(open(a.sol))
    s0 = evaluate(a.k, json.dumps(sol), inst.txt)[0]
    new, gain, desc = search(inst, sol, a.quiet)
    txt = json.dumps(new)
    s1, ok, msg = evaluate(a.k, txt, inst.txt)
    print(f"m8_apply {os.path.basename(a.sol)} : {s0} -> {s1} valide={ok} {msg if not ok else ''} gain théorique {gain} : {desc}")
    if a.out and ok and s1 > s0:
        open(a.out, "w").write(txt)
    if a.save and ok and s1 > s0:
        save_if_better(a.k, txt, method=a.method, dataset_txt=inst.txt)
    sys.exit(0 if ok and s1 > s0 else 1)

if __name__ == "__main__":
    main()
