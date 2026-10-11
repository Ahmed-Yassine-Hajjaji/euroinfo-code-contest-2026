#!/usr/bin/env python3
"""LNS (partie B de notes/ANALYSE.md) : part de best/instance_k.json, détruit k modèles, reconstruit en glouton.

Destruction : k modèles entraînés (aléatoires / pire ratio / partageant un type), avec leurs générateurs.
Reconstruction : modèles retirés + échantillon de modèles inutilisés, triés par priorité bruitée ; pour chacun,
options plein tarif / demi-tarif (données ou générateur au cas par cas) / tout-générateur ; on garde le meilleur
ratio valeur/coût. Acceptation si score >= courant (plateaux autorisés), sinon retour arrière exact.

Usage : python src/lns.py <instance> --seed S --time T [--save] [--start fichier.json]
"""
import argparse
import json
import math
import os
import random
import sys
import time
from bisect import bisect_left, insort

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance, Pools  # noqa: E402


class State:
    def __init__(self, inst, prices):
        self.inst = inst
        self.pools = Pools(inst)
        nm = len(inst.value)
        self.used = [0] * nm          # 0 libre, 1 entraîné, 2 générateur
        self.assign = {}              # m -> [(t, data_list, g ou -1)]
        self.gdata = {}               # g -> data_list
        self.energy = 0
        self.total = 0
        self.waste = 0
        self.lbt = [{t: lb for t, lb, _ in rq} for rq in inst.reqs]
        self.set_prices(prices)

    # ---------- prix et générateurs disponibles ----------
    def set_prices(self, prices):
        inst = self.inst
        self.alpha, self.beta, self.gamma = prices["alpha"], prices["beta"], prices["gamma"]
        self.lp = prices.get("lp")  # None ou (prix libre[t], prix total[t]) par unité de donnée
        self.select = prices.get("select", "ratio")
        self.zset = {}
        self.gkey = {}
        self.avail_gen = [[] for _ in range(4)]
        for g in range(len(inst.value)):
            if inst.gen_ok[g]:
                t, lb, _ = inst.reqs[g][0]
                self.gkey[g] = self.alpha * inst.energy[g] / inst.cap + self.dcost(t, lb, 1)
                if self.used[g] == 0:
                    self.avail_gen[t].append((self.gkey[g], g))
        for t in range(4):
            self.avail_gen[t].sort()

    def dcost(self, t, amount, c):
        if self.lp:
            pf, pt = self.lp
            return amount * (pt[t] if c else pt[t] + pf[t])
        return self.beta[t] * amount / self.inst.supply[t] * (self.gamma if c else 1.0)

    def _gen_add(self, g):
        if self.inst.gen_ok[g]:
            insort(self.avail_gen[self.inst.reqs[g][0][0]], (self.gkey[g], g))

    def _gen_del(self, g):
        if self.inst.gen_ok[g]:
            lst = self.avail_gen[self.inst.reqs[g][0][0]]
            j = bisect_left(lst, (self.gkey[g], g))
            if j < len(lst) and lst[j][1] == g:  # absent si la liste est restreinte (init LP)
                del lst[j]

    # ---------- valeur ----------
    def model_value(self, m, entries):
        defiled = any(g >= 0 or any(c for _, _, c in dl) for _, dl, g in entries)
        v = self.inst.value[m]
        return v // 2 if defiled else v

    # ---------- application / retrait exacts ----------
    def _take(self, dl):
        p = self.pools
        for s, i, c in dl:
            p.remove(p.p[p._t[i]][c], (s, i))

    def entries_waste(self, m, entries, gens):
        w = 0
        for t, dl, g in entries:
            w += sum(x[0] for x in dl) - (self.lbt[m][t] if g < 0 else 0)
        for g, dl in gens.items():
            w += sum(x[0] for x in dl) - self.inst.reqs[g][0][1]
        return w

    def apply(self, m, entries, gens):
        """entries = [(t, data_list, g)], gens = {g: data_list}."""
        inst = self.inst
        self.waste += self.entries_waste(m, entries, gens)
        for _, dl, _ in entries:
            self._take(dl)
        for g, dl in gens.items():
            self._take(dl)
            self.used[g] = 2
            self._gen_del(g)
            self.gdata[g] = dl
            self.energy += inst.energy[g]
        self.used[m] = 1
        self._gen_del(m)
        self.assign[m] = entries
        self.energy += inst.energy[m]
        self.total += self.model_value(m, entries)

    def remove(self, m):
        inst = self.inst
        entries = self.assign.pop(m)
        gens = {}
        for _, dl, g in entries:
            self.pools.undo(dl)
            if g >= 0:
                gdl = self.gdata.pop(g)
                self.pools.undo(gdl)
                gens[g] = gdl
                self.used[g] = 0
                self._gen_add(g)
                self.energy -= inst.energy[g]
        self.used[m] = 0
        self._gen_add(m)
        self.energy -= inst.energy[m]
        self.total -= self.model_value(m, entries)
        self.waste -= self.entries_waste(m, entries, gens)
        return (m, entries, gens)

    # ---------- construction d'options ----------
    gen_tries = 8  # nb de générateurs dont le remplissage peut échouer avant d'abandonner

    def _pick_gen(self, t, m, exclude, e_budget, tries=None):
        inst = self.inst
        n = 0
        tries = tries or self.gen_tries
        p = self.pools.p[t]
        smin = min((lst[0][0] for lst in p if lst), default=1 << 60)  # plus petit dataset dispo du type
        for key, g in self.avail_gen[t]:
            if g == m or g in exclude or inst.energy[g] > e_budget:
                continue
            _, lb, ub = inst.reqs[g][0]
            if ub < smin:  # fenêtre non remplissable (plus de dataset assez petit) : ne compte pas comme essai
                continue
            dl = self.pools.fill(t, lb, ub, [1]) or self.pools.fill(t, lb, ub, [1, 0])
            if dl is not None:
                return g, dl
            n += 1
            if n >= tries:
                break
        return None

    def _build(self, m, mode, e_left):
        """Construit une option ; retire temporairement les données puis les remet. Retourne l'option ou None."""
        inst = self.inst
        p = self.pools
        entries, gens = [], {}
        e_tot = inst.energy[m]
        cost = self.alpha * e_tot / inst.cap
        ok = True
        for t, lb, ub in inst.reqs[m]:
            dl, g = None, -1
            if mode == "full":
                dl = p.fill(t, lb, ub, [0])
            elif mode == "z" and t not in self.zset.get(m, ()):
                dl = p.fill(t, lb, ub, [1]) or p.fill(t, lb, ub, [1, 0])
            elif mode in ("allgen", "z") or lb > ub:
                r = self._pick_gen(t, m, gens, e_left - e_tot)
                if r:
                    g, gdl = r
            else:  # half : données ou générateur selon le coût estimé
                gl = self.avail_gen[t]
                gc = gl[0][0] if gl else math.inf
                if gc < self.dcost(t, lb, 1):
                    r = self._pick_gen(t, m, gens, e_left - e_tot)
                    if r:
                        g, gdl = r
                    else:
                        dl = p.fill(t, lb, ub, [1]) or p.fill(t, lb, ub, [1, 0])
                else:
                    dl = p.fill(t, lb, ub, [1]) or p.fill(t, lb, ub, [1, 0])
                    if dl is None:
                        r = self._pick_gen(t, m, gens, e_left - e_tot)
                        if r:
                            g, gdl = r
            if g >= 0:
                gens[g] = gdl
                e_tot += inst.energy[g]
                cost += self.alpha * inst.energy[g] / inst.cap + sum(self.dcost(t, s, c) for s, _, c in gdl)
                entries.append((t, [], g))
            elif dl is not None:
                cost += sum(self.dcost(t, s, c) for s, _, c in dl)
                entries.append((t, dl, -1))
            else:
                ok = False
                break
        for _, dl, _ in entries:
            p.undo(dl)
        for gdl in gens.values():
            p.undo(gdl)
        if not ok or e_tot > e_left:
            return None
        val = self.model_value(m, entries)
        key = val - cost if self.select == "profit" else val / max(cost, 1e-12)
        return (key, entries, gens)

    def try_insert(self, m, modes):
        inst = self.inst
        e_left = inst.cap - self.energy
        if inst.energy[m] > e_left or self.used[m]:
            return False
        best = None
        for mode in modes:
            if mode == "full" and any(lb > ub for _, lb, ub in inst.reqs[m]):
                continue
            o = self._build(m, mode, e_left)
            if o and (best is None or o[0] > best[0]):
                best = o
        if best is None:
            return False
        self.apply(m, best[1], best[2])
        return True

    # ---------- ré-empaquetage exact de 2-3 créneaux (réduction du gaspillage) ----------
    def repack(self, slots, extra=4, nmax=9):
        """slots : liste de ("m", m, idx) (entrée idx de assign[m], sans générateur) ou ("g", g) (créneau d'un
        générateur), tous du même type t. Redistribue leurs datasets (+ jusqu'à `extra` petits datasets libres du
        pool) pour minimiser la consommation totale, fenêtres respectées, plein tarif = libres seulement.
        Retourne le gain de données (>0 si amélioré, 0 sinon)."""
        inst = self.inst
        p = self.pools
        descr = []  # (lb, ub, only_free, dl)
        t = None
        for sl in slots:
            if sl[0] == "m":
                _, m, idx = sl
                tt, dl, g = self.assign[m][idx]
                if g >= 0:
                    return 0
                lb, ub = self.lbt[m][tt], next(u for x, _, u in inst.reqs[m] if x == tt)
                only_free = not any(gg >= 0 or any(c for _, _, c in d2) for _, d2, gg in self.assign[m])
                descr.append((lb, ub, only_free, dl))
            else:
                _, g = sl
                tt, lb, ub = inst.reqs[g][0]
                descr.append((lb, ub, False, self.gdata[g]))
            if t is None:
                t = tt
            elif tt != t:
                return 0
        items = [x for d in descr for x in d[3]]
        old_total = sum(x[0] for x in items)
        # petits datasets libres du pool (libres d'abord, puis copyrightés si un créneau les accepte)
        for c in (0, 1):
            if c == 1 and all(d[2] for d in descr):
                break
            lst = p.p[t][c]
            for x in lst[:extra]:
                items.append((x[0], x[1], c))
        if len(items) > nmax:
            items = items[:nmax]  # on garde en priorité les datasets des créneaux (en tête)
        n = len(items)
        k = len(descr)
        sizes = [x[0] for x in items]
        # énumération des affectations item -> créneau (0..k-1) ou libre (k), par récursion avec bornes
        best = [old_total, None]
        sums = [0] * k
        assign = [k] * n
        lbs = [d[0] for d in descr]; ubs = [d[1] for d in descr]
        rest = [0] * (n + 1)
        for i in range(n - 1, -1, -1):
            rest[i] = rest[i + 1] + sizes[i]

        def rec(i, tot):
            if tot >= best[0]:
                return
            if i == n:
                if all(lbs[j] <= sums[j] <= ubs[j] for j in range(k)):
                    best[0] = tot; best[1] = assign[:]
                return
            # borne : les créneaux sous lb doivent pouvoir être complétés avec le reste
            need = sum(max(0, lbs[j] - sums[j]) for j in range(k))
            if need > rest[i]:
                return
            sz, _, c = items[i]
            for j in range(k):
                if c and descr[j][2]:
                    continue
                if sums[j] + sz <= ubs[j]:
                    sums[j] += sz; assign[i] = j
                    rec(i + 1, tot + sz)
                    sums[j] -= sz
            assign[i] = k
            rec(i + 1, tot)

        rec(0, 0)
        if best[1] is None:
            return 0
        # application
        new_dls = [[] for _ in range(k)]
        for i, j in enumerate(best[1]):
            if j < k:
                new_dls[j].append(items[i])
        # datasets : retirer du pool ceux pris, remettre ceux libérés
        old_set = {x[1] for d in descr for x in d[3]}
        new_set = {x[1] for dl in new_dls for x in dl}
        for x in items:
            if x[1] in new_set and x[1] not in old_set:
                p.remove(p.p[t][x[2]], (x[0], x[1]))
            elif x[1] in old_set and x[1] not in new_set:
                insort(p.p[t][x[2]], (x[0], x[1]))
        for sl, dl in zip(slots, new_dls):
            dl.sort()
            if sl[0] == "m":
                _, m, idx = sl
                old_val = self.model_value(m, self.assign[m])
                tt, _, g = self.assign[m][idx]
                self.assign[m][idx] = (tt, dl, g)
                self.total += self.model_value(m, self.assign[m]) - old_val
            else:
                self.gdata[sl[1]] = dl
        self.waste -= old_total - best[0]
        return old_total - best[0]

    # ---------- chargement / export ----------
    def load(self, sol):
        inst = self.inst
        src = {s: t for s, t in sol["modelMappings"]}
        gen_of = {}
        for s, t in sol["modelMappings"]:
            gen_of[(t, inst.reqs[s][0][0])] = s
        byd = {}
        for d, m in sol["dataMappings"]:
            byd.setdefault(m, []).append(d)
        trained = (set(byd) | {t for t in src.values()}) - set(src)
        for m in trained:
            entries, gens = [], {}
            ds = byd.get(m, [])
            for t, lb, ub in inst.reqs[m]:
                g = gen_of.get((m, t), -1)
                dl = [(inst.ds[d][1], d, inst.ds[d][2]) for d in ds if inst.ds[d][0] == t]
                if g >= 0:
                    gens[g] = [(inst.ds[d][1], d, inst.ds[d][2]) for d in byd.get(g, [])]
                entries.append((t, dl, g))
            self.apply(m, entries, gens)

    def export(self):
        dm, mm = [], []
        for m, entries in self.assign.items():
            for _, dl, g in entries:
                dm.extend([i, m] for _, i, _ in dl)
                if g >= 0:
                    mm.append([g, m])
                    dm.extend([i, g] for _, i, _ in self.gdata[g])
        return {"dataMappings": dm, "modelMappings": mm}


def static_priority(st, m):
    inst = st.inst
    rq = inst.reqs[m]
    v = inst.value[m]
    e = st.alpha * inst.energy[m] / inst.cap
    best = 0.0
    if all(lb <= ub for _, lb, ub in rq):
        best = v / max(e + sum(st.dcost(t, lb, 0) for t, lb, _ in rq), 1e-12)
    ch = e
    for t, lb, ub in rq:
        gl = st.avail_gen[t]
        gc = gl[min(len(gl) - 1, len(gl) // 5)][0] if gl else math.inf
        ch += min(st.dcost(t, lb, 1) if lb <= ub else math.inf, gc)
    if ch < math.inf:
        best = max(best, (v // 2) / max(ch, 1e-12))
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--time", type=float, default=60)
    ap.add_argument("--start", default=None, help="solution de départ (défaut best/instance_k.json)")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--save-every", type=float, default=120)
    ap.add_argument("--kmax", type=int, default=10)
    ap.add_argument("--sample", type=int, default=150, help="modèles inutilisés tirés par réparation")
    ap.add_argument("--b", type=float, default=None, help="multiplicateur de beta (défaut: tiré au hasard)")
    ap.add_argument("--alpha", type=float, default=1.0)
    ap.add_argument("--noise", type=float, default=0.3)
    ap.add_argument("--temp", type=float, default=0.0, help="température du recuit (en points de score), 0 = >=")
    ap.add_argument("--sync", action="store_true", help="recharge best/ s'il est meilleur, à chaque sauvegarde")
    ap.add_argument("--lp", action="store_true", help="prix = duaux LP (runs/lp_k.json), priorités = solution LP")
    ap.add_argument("--init", choices=["best", "lp"], default="best", help="départ : best/ ou glouton guidé LP")
    ap.add_argument("--pscale", type=float, default=1.0, help="multiplicateur aléatoire max des prix LP (bruit)")
    ap.add_argument("--pair-tries", type=int, default=40, help="effort de recherche de paires (excès minimal)")
    ap.add_argument("--mu", type=float, default=0.0,
                    help="poids du gaspillage dans l'acceptation, en multiple du prix dual LP des données")
    ap.add_argument("--cp", type=float, default=0.0, help="probabilité d'un mouvement CP-SAT par itération")
    ap.add_argument("--cp-slots", type=int, default=60)
    ap.add_argument("--cp-new", type=int, default=30)
    ap.add_argument("--cp-time", type=float, default=2.0)
    ap.add_argument("--verbose-cp", action="store_true")
    ap.add_argument("--target", type=int, default=0, help="arrêt dès que ce score est atteint")
    ap.add_argument("--until", type=float, default=0, help="heure de fin absolue (epoch UNIX) ; prioritaire sur --time")
    ap.add_argument("--cp-workers", type=int, default=1)
    ap.add_argument("--roles", default=None, help="fichier de rôles (f,h,y,z) pour --init lp, ex. runs/mip_4.json")
    ap.add_argument("--tag", default="", help="suffixe du fichier runs/lns_<k>_s<seed><tag>.json")
    ap.add_argument("--exact", type=int, default=0, help="subset-sum exact si <= N éléments candidats (0 = off)")
    ap.add_argument("--tol", type=int, default=0, help="excès toléré sans chercher de paire")
    ap.add_argument("--dump-cur", action="store_true", help="écrit aussi l'état courant dans runs/..._cur.json")
    ap.add_argument("--guide", default=None, help="path relinking : solution cible dont on importe les modèles (avec leurs paquets)")
    ap.add_argument("--guide-p", type=float, default=0.02, help="probabilité d'un mouvement guidé par itération")
    ap.add_argument("--guide-tol", type=float, default=150.0, help="perte de score tolérée pour un mouvement guidé (path relinking)")
    ap.add_argument("--repack", type=float, default=0.0, help="probabilité d'un ré-empaquetage exact de 2-3 créneaux")
    ap.add_argument("--gen-tries", type=int, default=8, help="générateurs non remplissables tolérés avant abandon")
    ap.add_argument("--bias", type=float, default=0.0, help="biais des candidats vers les meilleures priorités (0 = uniforme)")
    a = ap.parse_args()
    if a.until:
        a.time = max(0.0, a.until - time.time())
    import signal
    stop = {"flag": False}

    def _term(signum, frame):  # arrêt propre : on sort de la boucle et on sauvegarde
        stop["flag"] = True
    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)

    rng = random.Random(a.seed)
    inst = Instance(a.instance)
    tension = [inst.demand[t] / inst.supply[t] for t in range(4)]
    b = a.b if a.b is not None else math.exp(rng.uniform(math.log(0.02), math.log(1.5)))
    prices = {"alpha": a.alpha, "beta": [b * x for x in tension], "gamma": rng.uniform(0.2, 1.0)}
    lpsol = None
    if a.lp:
        with open(os.path.join(ROOT, "runs", f"lp_{a.instance}.json")) as f:
            lpsol = json.load(f)
        sc = lambda: math.exp(rng.uniform(-math.log(a.pscale), math.log(a.pscale))) if a.pscale > 1 else 1.0
        e_sc = sc()
        prices = {"alpha": lpsol["dual_energy"] * e_sc, "beta": [0] * 4, "gamma": 1.0, "select": "profit",
                  "lp": ([x * sc() for x in lpsol["dual_free"]], [x * sc() for x in lpsol["dual_total"]])}
        b = e_sc
    st = State(inst, prices)
    st.pools.pair_tries, st.pools.tol, st.pools.exact = a.pair_tries, a.tol, a.exact
    st.gen_tries = a.gen_tries
    nm = len(inst.value)
    start = a.start or os.path.join(ROOT, "best", f"instance_{a.instance}.json")
    if lpsol:
        # priorité = part LP entraînée (f + h), départagée par le ratio valeur/coût aux prix duaux
        sp = [static_priority(st, m) for m in range(nm)]
        mx = max(sp) or 1.0
        prio = [lpsol["f"][m] + lpsol["h"][m] + 1e-3 * sp[m] / mx for m in range(nm)]
    else:
        prio = [static_priority(st, m) for m in range(nm)]
    if a.init == "lp" and a.roles:
        with open(a.roles) as f:
            ro = json.load(f)
        lpsol = dict(lpsol, f=ro["f"], h=ro["h"], y=ro["y"], z=ro["z"])
        sp = [static_priority(st, m) for m in range(nm)]
        mx = max(sp) or 1.0
        prio = [lpsol["f"][m] + lpsol["h"][m] + 1e-3 * sp[m] / mx for m in range(nm)]
    if a.init == "lp":
        # 1) rôles LP : générateurs réservés = y > 0.5 ; plein tarif = f ; demi = h avec besoins z couverts par générateur
        Y = {m for m in range(nm) if lpsol["y"][m] > 0.5}
        saved_av = st.avail_gen
        st.avail_gen = [[(k_, g) for k_, g in lst if g in Y] for lst in saved_av]
        st.zset = {m: set(lpsol["z"][m]) for m in range(nm)}
        order = sorted(range(nm), key=lambda m: -prio[m])
        for m in order:
            if lpsol["f"][m] > 0.5:
                st.try_insert(m, ["full"])
        for m in order:
            if lpsol["h"][m] > 0.5:
                st.try_insert(m, ["z"])
        print(f"  rôles LP : {st.total} énergie {st.energy/inst.cap:.4f}", flush=True)
        # 2) on rend tous les générateurs et on complète
        used_g = {g for g in st.gdata}
        st.avail_gen = [[(k_, g) for k_, g in lst if g not in used_g and st.used[g] == 0] for lst in saved_av]
        for m in order:
            if prio[m] > 0:
                st.try_insert(m, ["full", "half", "allgen"])
        print(f"  glouton LP : {st.total} énergie {st.energy/inst.cap:.4f}", flush=True)
    else:
        with open(start) as f:
            st.load(json.load(f))
    mu = 0.0
    if a.mu and lpsol:
        mu = a.mu * sum(lpsol["dual_total"][t] + lpsol["dual_free"][t] for t in range(4)) / 4
    print(f"  mu = {mu:.3e} par unité de donnée gaspillée ; gaspillage initial {st.waste}", flush=True)
    cand_pool = sorted((m for m in range(nm) if prio[m] > 0), key=lambda m: -prio[m])
    start_total = st.total
    print(f"inst {a.instance} seed {a.seed} départ {st.total} énergie {st.energy/inst.cap:.4f} "
          f"b={b:.3f} gamma={prices['gamma']:.2f}", flush=True)

    t0 = time.time()
    last_save = t0
    saved_total = -1  # la 1re sauvegarde passe toujours par save_if_better (qui compare à best/)
    it = acc = imp = 0
    all_modes = ["full", "half", "allgen"]

    best_total = st.total
    best_sol = None  # None = l'état courant EST la meilleure solution

    def save():
        nonlocal saved_total, st, best_total, best_sol
        if a.dump_cur:  # état COURANT (pas le meilleur) : paquets différents pour rematch --extra-sols
            with open(os.path.join(ROOT, "runs", f"lns_{a.instance}_s{a.seed}{a.tag}_cur.json"), "w") as f:
                f.write(json.dumps(st.export(), separators=(",", ":")))
        sol = best_sol if best_sol is not None else st.export()
        txt = json.dumps(sol, separators=(",", ":"))
        out = os.path.join(ROOT, "runs", f"lns_{a.instance}_s{a.seed}{a.tag}.json")
        with open(out, "w") as f:
            f.write(txt)
        if a.save and best_total > saved_total:
            from save_if_better import save_if_better
            save_if_better(a.instance, txt, method=f"lns seed={a.seed} b={b:.3f} gamma={prices['gamma']:.2f}",
                           dataset_txt=inst.txt)
        saved_total = max(saved_total, best_total)
        if a.sync:
            try:
                with open(os.path.join(ROOT, "best", "scores.json")) as f:
                    bs = json.load(f)[str(a.instance)]["score"]
            except Exception:
                bs = 0
            if bs > best_total:
                with open(start) as f:
                    sol = json.load(f)
                st = State(inst, prices)
                st.pools.pair_tries, st.pools.tol, st.pools.exact = a.pair_tries, a.tol, a.exact
                st.gen_tries = a.gen_tries
                st.load(sol)
                best_total, best_sol, saved_total = st.total, None, st.total
                print(f"  sync: rechargé best/ ({st.total})", flush=True)

    guide = None
    gd_done = set()
    gd_stats = [0, 0, 0]  # mouvements guidés : essais, acceptés, modèles cibles importés
    if a.guide:
        with open(a.guide) as f:
            gsol = json.load(f)
        gsrc = {s_: t_ for s_, t_ in gsol["modelMappings"]}
        ggen = {(t_, inst.reqs[s_][0][0]): s_ for s_, t_ in gsol["modelMappings"]}
        gbyd = {}
        for d, m in gsol["dataMappings"]:
            gbyd.setdefault(m, []).append(d)
        guide = {}
        for m in (set(gbyd) | set(gsrc.values())) - set(gsrc):
            entries, gens = [], {}
            for t, lb, ub in inst.reqs[m]:
                g = ggen.get((m, t), -1)
                dl = sorted((inst.ds[d][1], d, inst.ds[d][2]) for d in gbyd.get(m, []) if inst.ds[d][0] == t)
                if g >= 0:
                    gens[g] = sorted((inst.ds[d][1], d, inst.ds[d][2]) for d in gbyd.get(g, []))
                entries.append((t, dl, g))
            guide[m] = (entries, gens)
        print(f"  guide : {len(guide)} modèles cibles, dont {sum(1 for m in guide if st.used[m] == 0)} absents du départ", flush=True)
    cp_stats = [0, 0, 0]  # essais, améliorations (valeur ou gaspillage), gain de valeur
    rp_stats = [0, 0, 0]  # repack : essais, succès, données libérées

    def repair_sample():
        cands = set()
        for _ in range(a.sample):
            u = rng.random()
            m = cand_pool[int(len(cand_pool) * u ** (1.0 + a.bias))]
            if st.used[m] == 0:
                cands.add(m)
        for m in sorted(cands, key=lambda m: -prio[m] * math.exp(a.noise * rng.gauss(0, 1))):
            st.try_insert(m, all_modes)

    while time.time() - t0 < a.time and not (a.target and best_total >= a.target) and not stop["flag"]:
        it += 1
        trained = list(st.assign)
        if not trained:
            break
        if a.cp > 0 and rng.random() < a.cp:
            from cpsat_repair import cp_move
            before = st.total
            r = cp_move(st, rng, n_slots=a.cp_slots, n_new=a.cp_new, tlimit=a.cp_time, workers=a.cp_workers)
            cp_stats[0] += 1
            if r is not None:
                cp_stats[1] += 1
                repair_sample()
                cp_stats[2] += st.total - before
                if a.verbose_cp:
                    print(f"  cp t={r['t']} val {r['old_val']}->{r['new_val']} gasp {r['old_w']}->{r['new_w']} "
                          f"retirés {len(r['dropped'])} {r['status']} | total {before}->{st.total}", flush=True)
            if st.total > best_total:
                best_total, best_sol = st.total, None
            continue
        if guide and rng.random() < a.guide_p:
            absent = [m for m in guide if st.used[m] == 0 and m not in gd_done]
            if not absent:
                guide = None  # chemin terminé : LNS normal depuis l'état courant (le meilleur est conservé)
                print(f"  guide : chemin terminé à it={it}, best={best_total}", flush=True)
                continue
            m0 = rng.choice(absent)
            gd_done.add(m0)
            entries, gens = guide[m0]
            # modèles courants qui occupent ses datasets ou ses générateurs
            dmap = {}
            for m, ents in st.assign.items():
                for _, dl, g in ents:
                    for _, i, _ in dl:
                        dmap[i] = m
                    if g >= 0:
                        for _, i, _ in st.gdata[g]:
                            dmap[i] = m
            victims = set()
            for _, dl, g in entries:
                for _, i, _ in dl:
                    if i in dmap:
                        victims.add(dmap[i])
                if g >= 0:
                    if st.used[g] == 1:
                        victims.add(g)
                    elif st.used[g] == 2:
                        victims.add(next(mm for mm, ents in st.assign.items() if any(gg == g for _, _, gg in ents)))
                    for _, i, _ in gens[g]:
                        if i in dmap:
                            victims.add(dmap[i])
            victims = [v for v in victims if v in st.assign]
            if len(victims) > a.kmax:
                continue
            old_total, old_waste = st.total, st.waste
            removed = [st.remove(v) for v in victims]
            # énergie : libérer les modèles de plus faible priorité si besoin
            need = inst.energy[m0] + sum(inst.energy[g] for g in gens) - (inst.cap - st.energy)
            if need > 0:
                for v in sorted(st.assign, key=lambda m: prio[m])[:40]:
                    if need <= 0:
                        break
                    rec = st.remove(v); removed.append(rec)
                    need -= inst.energy[v] + sum(inst.energy[g] for g in rec[2])
            ok = need <= 0 and all(st.used[g] == 0 for g in gens)
            if ok:
                st.apply(m0, [(t, list(dl), g) for t, dl, g in entries], {g: list(dl) for g, dl in gens.items()})
            added = [m0] if ok else []
            repair_sample_added = []
            cands = set(v for v, _, _ in removed)
            for _ in range(a.sample):
                u = rng.random()
                m = cand_pool[int(len(cand_pool) * u ** (1.0 + a.bias))]
                if st.used[m] == 0:
                    cands.add(m)
            for m in sorted(cands, key=lambda m: -prio[m] * math.exp(a.noise * rng.gauss(0, 1))):
                if st.try_insert(m, all_modes):
                    added.append(m)
            gd_stats[0] += 1
            delta = st.total - old_total - mu * (st.waste - old_waste)
            if st.total < old_total:
                delta = st.total - old_total
            # path relinking : on accepte de perdre jusqu'à guide_tol points pour importer un modèle cible
            if (ok and delta >= -a.guide_tol) or delta >= 0 or (a.temp > 0 and rng.random() < math.exp(delta / a.temp)):
                if delta < 0 and best_sol is None:
                    best_sol = None  # on photographie : plus simple, on exporte avant de bouger
                    new_total = st.total
                    added_recs = [st.remove(m) for m in added]
                    for m, entries_, gens_ in removed:
                        st.apply(m, entries_, gens_)
                    best_sol = st.export()
                    for m, _, _ in removed:
                        st.remove(m)
                    for m, entries_, gens_ in added_recs:
                        st.apply(m, entries_, gens_)
                    assert st.total == new_total
                gd_stats[1] += 1
                if ok:
                    gd_stats[2] += 1
                acc += 1
                if st.total > best_total:
                    best_total, best_sol = st.total, None
            else:
                for m in added:
                    st.remove(m)
                for m, entries_, gens_ in removed:
                    st.apply(m, entries_, gens_)
                assert st.total == old_total
            continue
        if a.repack > 0 and rng.random() < a.repack:
            # ré-empaquetage : 2 ou 3 créneaux du même type (modèles ou générateurs), tirés au hasard
            t = rng.randrange(4)
            cands = []
            for m in rng.sample(trained, min(40, len(trained))):
                for idx, (tt, dl, g) in enumerate(st.assign[m]):
                    if tt == t and g < 0 and dl:
                        cands.append(("m", m, idx))
                    elif tt == t and g >= 0:
                        cands.append(("g", g))
            if len(cands) >= 2:
                sl = rng.sample(cands, rng.choice((2, 2, 3)) if len(cands) >= 3 else 2)
                gain = st.repack(sl)
                rp_stats[0] += 1
                if gain > 0:
                    rp_stats[1] += 1; rp_stats[2] += gain
                    repair_sample()
                    if st.total > best_total:
                        best_total, best_sol = st.total, None
            continue
        k = rng.randint(1, a.kmax)
        op = rng.random()
        if op < 0.4:
            victims = rng.sample(trained, min(k, len(trained)))
        elif op < 0.7:
            pool = rng.sample(trained, min(4 * k, len(trained)))
            pool.sort(key=lambda m: prio[m])
            victims = pool[:k]
        else:
            t = rng.randrange(4)
            pool = [m for m in rng.sample(trained, min(60 * k, len(trained)))
                    if any(tt == t for tt, _, _ in inst.reqs[m])]
            victims = pool[:k]
        old_total, old_waste = st.total, st.waste
        removed = [st.remove(m) for m in victims]
        cands = set(victims)
        for _ in range(a.sample):
            u = rng.random()
            m = cand_pool[int(len(cand_pool) * u ** (1.0 + a.bias))]
            if st.used[m] == 0:
                cands.add(m)
        order = sorted(cands, key=lambda m: -prio[m] * math.exp(a.noise * rng.gauss(0, 1)))
        added = [m for m in order if st.try_insert(m, all_modes)]
        delta = st.total - old_total - mu * (st.waste - old_waste)
        if st.total < old_total:
            delta = st.total - old_total  # une baisse de valeur n'est acceptée que par le recuit
        if delta >= 0 or (a.temp > 0 and rng.random() < math.exp(delta / a.temp)):
            if delta < 0 and best_sol is None:
                # on quitte la meilleure solution : on la photographie (en remettant l'état d'avant)
                new_total = st.total
                added_recs = [st.remove(m) for m in added]
                for m, entries, gens in removed:
                    st.apply(m, entries, gens)
                best_sol = st.export()
                for m, _, _ in removed:
                    st.remove(m)
                for m, entries, gens in added_recs:
                    st.apply(m, entries, gens)
                assert st.total == new_total
            acc += 1
            if delta > 0:
                imp += 1
            if st.total > best_total:
                best_total, best_sol = st.total, None
        else:
            for m in added:
                st.remove(m)
            for m, entries, gens in removed:
                st.apply(m, entries, gens)
            assert st.total == old_total
        if time.time() - last_save > a.save_every:
            last_save = time.time()
            print(f"  t={time.time()-t0:.0f}s it={it} acc={acc} imp={imp} total={st.total} best={best_total} "
                  f"gaspillage={st.waste} cp={cp_stats} rp={rp_stats} gd={gd_stats} "
                  f"(+{best_total-start_total}) énergie {st.energy/inst.cap:.4f}", flush=True)
            save()
    save()
    print(f"FIN inst {a.instance} seed {a.seed}: {start_total} -> {best_total} it={it} acc={acc} imp={imp}")


if __name__ == "__main__":
    main()
