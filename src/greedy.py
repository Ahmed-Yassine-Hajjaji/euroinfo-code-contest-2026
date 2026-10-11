#!/usr/bin/env python3
"""Glouton constructif (partie A de notes/ANALYSE.md).

- Prix des ressources : énergie (alpha) et données par type (beta_t), tirés aléatoirement autour de
  valeurs par défaut ; ordre des modèles = ratio valeur / coût estimé, bruité.
- Pour chaque modèle, deux options : plein tarif (datasets libres seuls) ou demi-tarif (copyrightés d'abord,
  générateurs possibles). On garde l'option faisable au meilleur ratio valeur / coût réel.
- Remplissage d'un besoin : gros datasets d'abord, puis le plus petit « finisseur » qui fait tomber la somme dans
  [lb, ub], avec essai de paires quand le reste est proche (excès minimal).

Usage : python src/greedy.py <instance> [--seed S] [--iters N] [--time T] [--save]
"""
import argparse
import json
import math
import os
import random
import sys
import time
from bisect import bisect_left, bisect_right, insort

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
TYPES = "ntic"


class Instance:
    def __init__(self, k):
        self.k = k
        with open(os.path.join(ROOT, "datasets", f"instance_{k}.json")) as f:
            self.txt = f.read()
        d = json.loads(self.txt)
        self.cap = d["energyCap"]
        self.value = [m["value"] for m in d["models"]]
        self.energy = [m["energyCost"] for m in d["models"]]
        # reqs[m] = [(type_idx, lb, ub), ...]
        self.reqs = [[(TYPES.index(t), r["lowerBound"], r["upperBound"])
                      for t, r in m["dataRequirements"].items()] for m in d["models"]]
        self.ds = [(TYPES.index(x["dataType"]), x["size"], x["isCopyrighted"]) for x in d["datasets"]]
        self.supply = [0] * 4
        for t, s, _ in self.ds:
            self.supply[t] += s
        self.supply = [max(s, 1) for s in self.supply]
        self.demand = [0] * 4
        for rq in self.reqs:
            for t, lb, ub in rq:
                if lb <= ub:
                    self.demand[t] += lb
        # générateurs possibles : mono-besoin réalisable
        self.gen_ok = [len(rq) == 1 and rq[0][1] <= rq[0][2] for rq in self.reqs]


class Pools:
    """Datasets disponibles, triés par taille, par (type, copyright)."""

    def __init__(self, inst):
        self.p = [[[], []] for _ in range(4)]
        self._t = [t for t, _, _ in inst.ds]
        self.exact = 0        # si > 0 : subset-sum exact quand le nb d'éléments candidats <= exact
        self.pair_tries = 40  # nb de premiers éléments essayés pour une paire
        self.tol = 0          # excès toléré avant de chercher une paire
        for i, (t, s, c) in enumerate(inst.ds):
            self.p[t][c].append((s, i))
        for t in range(4):
            for c in range(2):
                self.p[t][c].sort()

    def remove(self, lst, item):
        j = bisect_left(lst, item)
        del lst[j]

    def fill(self, t, lb, ub, cs):
        """Prend des datasets de type t dans les pools cs (liste de 0/1) pour une somme dans [lb, ub].
        Retourne la liste des (taille, id, c) pris (déjà retirés) ou None (rien n'est retiré)."""
        if lb > ub:
            return None
        lists = [(self.p[t][c], c) for c in cs]
        if self.exact:
            n = sum(bisect_right(lst, (ub, 1 << 60)) for lst, _ in lists)
            if n <= self.exact:
                return self.fill_exact(lists, lb, ub)
        taken = []
        cur = 0
        while True:
            r, room = lb - cur, ub - cur
            if r <= 0:
                return taken
            # 1) finisseur : plus petit élément dans [r, room]
            best = None
            for lst, c in lists:
                j = bisect_left(lst, (r, -1))
                if j < len(lst) and lst[j][0] <= room and (best is None or lst[j][0] < best[0][0]):
                    best = (lst[j], lst, c)
            mx = max((lst[-1][0] for lst, _ in lists if lst), default=0)
            if mx == 0:
                break
            # 2) paire finissante si le reste est petit et que le finisseur seul gaspille trop
            if r <= 2 * mx and (best is None or best[0][0] - r > self.tol):
                pair = self._pair(lists, r, room, self.pair_tries)
                if pair is not None and (best is None or pair[0][0][0] + pair[1][0][0] < best[0][0]):
                    for it, lst, c in pair:
                        self.remove(lst, it)
                        taken.append((it[0], it[1], c))
                    return taken
            if best is not None:
                it, lst, c = best
                self.remove(lst, it)
                taken.append((it[0], it[1], c))
                return taken
            # 3) plus gros élément < r
            best = None
            for lst, c in lists:
                j = bisect_left(lst, (r, -1)) - 1
                if j >= 0 and (best is None or lst[j][0] > best[0][0]):
                    best = (lst[j], lst, c)
            if best is None:
                break
            it, lst, c = best
            self.remove(lst, it)
            taken.append((it[0], it[1], c))
            cur += it[0]
        self.undo(taken)
        return None

    def fill_exact(self, lists, lb, ub):
        """Subset-sum exact (bitset sur entier Python) : somme minimale >= lb et <= ub. Retire et retourne."""
        items = [(it, lst, c) for lst, c in lists for it in lst[:bisect_right(lst, (ub, 1 << 60))]]
        # ordre décroissant : la reconstruction (qui saute un élément dès qu'on peut s'en passer avec les
        # précédents) privilégie alors les GROS datasets et garde les petits comme « monnaie »
        items.sort(key=lambda x: -x[0][0])
        mask = (1 << (ub + 1)) - 1
        reach = 1
        hist = [1]
        for it, _, _ in items:
            reach = (reach | (reach << it[0])) & mask
            hist.append(reach)
        hi = reach >> lb
        if not hi:
            return None
        target = lb + ((hi & -hi).bit_length() - 1)
        taken = []
        cur = target
        for j in range(len(items) - 1, -1, -1):
            if cur == 0:
                break
            if not (hist[j] >> cur) & 1:  # cur inatteignable sans l'élément j : on le prend
                it, lst, c = items[j]
                taken.append((it, lst, c))
                cur -= it[0]
        out = []
        for it, lst, c in taken:
            self.remove(lst, it)
            out.append((it[0], it[1], c))
        return out

    def _pair(self, lists, r, room, tries=40):
        best, best_ex = None, None
        for la, ca in lists:
            j = bisect_left(la, (r, -1)) - 1
            n = 0
            while j >= 0 and n < tries:
                a = la[j]
                if 2 * a[0] < r:  # le plus grand élément d'une paire est >= r/2 : déjà vu
                    break
                lo, hi = r - a[0], room - a[0]
                for lb_, cb in lists:
                    k = bisect_left(lb_, (lo, -1))
                    if lb_ is la and k < len(lb_) and lb_[k] == a:
                        k += 1
                    if k < len(lb_) and lb_[k][0] <= hi:
                        ex = a[0] + lb_[k][0] - r
                        if best_ex is None or ex < best_ex:
                            best_ex, best = ex, [(a, la, ca), (lb_[k], lb_, cb)]
                            if ex <= self.tol:
                                return best
                j -= 1
                n += 1
        return best

    def undo(self, taken):
        for s, i, c in taken:
            insort(self.p[self._t[i]][c], (s, i))


def solve(inst, rng, params):
    pools = Pools(inst)
    nm = len(inst.value)
    alpha = params["alpha"]
    beta = params["beta"]          # par type
    gamma = params["gamma"]        # remise sur le coût des données copyrightées
    noise = params["noise"]
    cap = inst.cap

    def data_cost(t, amount, cr):
        return beta[t] * amount / inst.supply[t] * (gamma if cr else 1.0)

    def gen_cost(g):
        t, lb, _ = inst.reqs[g][0]
        return alpha * inst.energy[g] / cap + data_cost(t, lb, True)

    # générateurs par type, triés par coût
    gens = [[] for _ in range(4)]
    for g in range(nm):
        if inst.gen_ok[g]:
            gens[inst.reqs[g][0][0]].append((gen_cost(g), g))
    for t in range(4):
        gens[t].sort()
    # coût de référence d'un générateur par type (quantile bas)
    gref = []
    for t in range(4):
        if gens[t]:
            gref.append(gens[t][min(len(gens[t]) - 1, int(len(gens[t]) * params["gq"]))][0])
        else:
            gref.append(math.inf)

    # priorité statique
    order = []
    for m in range(nm):
        rq = inst.reqs[m]
        v = inst.value[m]
        e = alpha * inst.energy[m] / cap
        best = 0.0
        if all(lb <= ub for _, lb, ub in rq):
            c = e + sum(data_cost(t, lb, False) for t, lb, _ in rq)
            best = v / max(c, 1e-12)
        ch = e
        for t, lb, ub in rq:
            dc = data_cost(t, lb, True) if lb <= ub else math.inf
            ch += min(dc, gref[t])
        if ch < math.inf:
            best = max(best, (v // 2) / max(ch, 1e-12))
        if best > 0:
            order.append((best * math.exp(noise * rng.gauss(0, 1)), m))
    order.sort(reverse=True)

    used = [0] * nm  # 0 libre, 1 entraîné, 2 générateur, 3 générateur réservé (provisoire)
    gptr = [0] * 4
    energy_left = cap
    data_map = []   # (dataset, model)
    model_map = []  # (source, target)
    total = 0

    def take_gen(t, target, e_budget):
        """Trouve et remplit un générateur de type t. Retourne (g, taken) ou None."""
        lst = gens[t]
        j = gptr[t]
        while j < len(lst) and used[lst[j][1]] in (1, 2):
            j += 1
        gptr[t] = j
        tries = 0
        while j < len(lst) and tries < 6:
            g = lst[j][1]
            j += 1
            if used[g] or g == target or inst.energy[g] > e_budget:
                continue
            tries += 1
            _, lb, ub = inst.reqs[g][0]
            tk = pools.fill(t, lb, ub, [1]) or pools.fill(t, lb, ub, [1, 0])
            if tk is not None:
                return g, tk
        return None

    for _, m in order:
        if used[m]:
            continue
        rq = inst.reqs[m]
        e_m = inst.energy[m]
        if e_m > energy_left:
            continue
        v = inst.value[m]
        options = []
        # option plein tarif
        if all(lb <= ub for _, lb, ub in rq):
            taken = []
            ok = True
            for t, lb, ub in rq:
                tk = pools.fill(t, lb, ub, [0])
                if tk is None:
                    ok = False
                    break
                taken.append(tk)
            if ok:
                cost = alpha * e_m / cap + sum(data_cost(t, s, False) for (t, _, _), tk in zip(rq, taken)
                                               for s, _, _ in tk)
                options.append((v / max(cost, 1e-12), "full", taken, [], e_m))
            for tk in taken:
                pools.undo(tk)
        # option demi-tarif
        taken, gl = [], []
        ok = True
        e_tot = e_m
        cost = alpha * e_m / cap
        for t, lb, ub in rq:
            dc = data_cost(t, lb, True) if lb <= ub else math.inf
            use_gen = gref[t] < dc
            tk = None
            if not use_gen:
                tk = pools.fill(t, lb, ub, [1]) or pools.fill(t, lb, ub, [1, 0])
                if tk is not None:
                    taken.append((t, tk))
                    cost += sum(data_cost(t, s, c) for s, _, c in tk)
                    continue
            r = take_gen(t, m, energy_left - e_tot)
            if r is None and use_gen and lb <= ub:
                tk = pools.fill(t, lb, ub, [1]) or pools.fill(t, lb, ub, [1, 0])
                if tk is not None:
                    taken.append((t, tk))
                    cost += sum(data_cost(t, s, c) for s, _, c in tk)
                    continue
            if r is None:
                ok = False
                break
            g, gtk = r
            used[g] = 3  # réservation provisoire
            gl.append((g, gtk))
            e_tot += inst.energy[g]
            cost += alpha * inst.energy[g] / cap + sum(data_cost(t, s, c) for s, _, c in gtk)
        if ok and e_tot <= energy_left:
            defiled = bool(gl) or any(c for _, tk in taken for _, _, c in tk)
            val = v // 2 if defiled else v
            options.append((val / max(cost, 1e-12), "half", [tk for _, tk in taken], gl, e_tot))
        # annule la réservation demi-tarif (on la refera si choisie)
        for _, tk in taken:
            pools.undo(tk)
        for g, gtk in gl:
            used[g] = 0
            pools.undo(gtk)
        if not options:
            continue
        options.sort(key=lambda o: -o[0])
        # ré-applique l'option choisie (les retraits ont été annulés : on reprend exactement les mêmes ids)
        for ratio, kind, taken, gl, e_tot in options:
            if e_tot > energy_left:
                continue
            for tk in taken:
                for s, i, c in tk:
                    pools.remove(pools.p[pools._t[i]][c], (s, i))
                    data_map.append((i, m))
            for g, gtk in gl:
                used[g] = 2
                for s, i, c in gtk:
                    pools.remove(pools.p[pools._t[i]][c], (s, i))
                    data_map.append((i, g))
                model_map.append((g, m))
            used[m] = 1
            energy_left -= e_tot
            defiled = bool(gl) or any(c for tk in taken for _, _, c in tk)
            total += v // 2 if defiled else v
            break

    sol = {"dataMappings": [[i, m] for i, m in data_map], "modelMappings": [[g, m] for g, m in model_map]}
    return total, sol


def default_params(inst, rng, randomize=True, bmin=0.02, bmax=20.0):
    # beta_t ~ tension de la ressource données du type t
    tension = [inst.demand[t] / inst.supply[t] for t in range(4)]
    if not randomize:
        return {"alpha": 1.0, "beta": [1.0 * x for x in tension], "gamma": 0.5, "noise": 0.0, "gq": 0.2}
    b = math.exp(rng.uniform(math.log(bmin), math.log(bmax)))
    return {
        "alpha": rng.choice([1.0, 1.0, 1.0, 0.0]),
        "beta": [b * tension[t] * math.exp(rng.uniform(-0.5, 0.5)) for t in range(4)],
        "gamma": rng.uniform(0.1, 1.0),
        "noise": rng.choice([0.0, 0.05, 0.15, 0.3]),
        "gq": rng.uniform(0.0, 0.5),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--iters", type=int, default=1)
    ap.add_argument("--time", type=float, default=1e9, help="limite de temps (s)")
    ap.add_argument("--save", action="store_true", help="passe la meilleure solution à save_if_better")
    ap.add_argument("--out", default=None)
    ap.add_argument("--bmin", type=float, default=0.02, help="borne basse du multiplicateur de beta")
    ap.add_argument("--bmax", type=float, default=20.0, help="borne haute du multiplicateur de beta")
    a = ap.parse_args()
    t0 = time.time()
    inst = Instance(a.instance)
    rng = random.Random(a.seed)
    best, best_sol, best_p = -1, None, None
    for it in range(a.iters):
        p = default_params(inst, rng, randomize=it > 0 or a.seed != 0, bmin=a.bmin, bmax=a.bmax)
        ts = time.time()
        score, sol = solve(inst, rng, p)
        print(f"inst {a.instance} seed {a.seed} it {it}: {score}  ({time.time()-ts:.1f}s) "
              f"alpha={p['alpha']} beta={[round(x, 3) for x in p['beta']]} gamma={p['gamma']:.2f} "
              f"noise={p['noise']} gq={p['gq']:.2f}", flush=True)
        if score > best:
            best, best_sol, best_p = score, sol, p
        if time.time() - t0 > a.time:
            break
    txt = json.dumps(best_sol, separators=(",", ":"))
    out = a.out or os.path.join(ROOT, "runs", f"greedy_{a.instance}_s{a.seed}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(txt)
    print(f"BEST inst {a.instance} seed {a.seed}: {best} params={json.dumps(best_p)}")
    if a.save:
        from save_if_better import save_if_better
        save_if_better(a.instance, txt, method=f"greedy seed={a.seed} params={json.dumps(best_p)}",
                       dataset_txt=inst.txt)


if __name__ == "__main__":
    main()
