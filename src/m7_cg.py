#!/usr/bin/env python3
"""m7 — Génération de colonnes + price-and-branch (HiGHS) pour l'instance 2 (et autres).

Idée : les données LIBRES sont la seule ressource dont l'empaquetage exact est difficile (toutes utilisées dans
best/2 ; copyrightées abondantes). Modèle maître (max valeur) :
  rôles f_m (plein tarif), h_m (demi), y_m (générateur), z_mt (besoin couvert par générateur) binaires ;
  colonnes λ_c = (créneau k=(m,t), sous-ensemble exact de datasets libres de type t, somme ∈ [lb, ub]) ;
  - chaque dataset libre dans ≤ 1 colonne ; - Σ_{c ∈ k} λ_c = f_m pour chaque créneau k de m ;
  - énergie ; - données totales par type (h, y, colonnes) ≤ offre ; - générateurs par type ; - f+h+y ≤ 1 ; z ≤ h.
Pricing : un DP de sac à dos par type (coût min Σ w_d à somme S exacte), partagé par tous les créneaux du type.
Puis MIP sur les colonnes générées (hint = best), réalisation des h/y avec les datasets copyrightés (+ libres restants).
Usage : python src/m7_cg.py 2 --time-cg 600 --time-mip 1200 --threads 12 --out runs/m7_cg_2.json [--save]
"""
import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance, Pools  # noqa: E402
from save_if_better import evaluate  # noqa: E402

INF = float("inf")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


class Master:
    def __init__(self, inst, threads=12, verbose=False, cand=None):
        """cand : ensemble des modèles candidats au plein tarif (None = tous les réalisables)."""
        self.inst = inst
        nm = len(inst.value)
        self.nm = nm
        self.T = [0] * 4
        for t, s, c in inst.ds:
            self.T[t] += s
        self.free = [[] for _ in range(4)]  # (size, id) datasets libres par type
        for i, (t, s, c) in enumerate(inst.ds):
            if not c:
                self.free[t].append((s, i))
        self.drow = {}  # dataset id -> ligne
        # --- lignes
        self.row_lo, self.row_hi = [], []
        r = 0
        for t in range(4):
            for s, i in self.free[t]:
                self.drow[i] = r; self.row_lo.append(-INF); self.row_hi.append(1.0); r += 1
        self.ffeas = [all(lb <= u for _, lb, u in inst.reqs[m]) and (cand is None or m in cand) for m in range(nm)]
        self.slots = []  # (m, t, lb, ub)
        self.srow = {}   # (m,t) -> ligne
        self.kidx = {}   # (m,t) -> index de créneau
        for m in range(nm):
            if self.ffeas[m]:
                for t, lb, u in inst.reqs[m]:
                    self.srow[(m, t)] = r; self.kidx[(m, t)] = len(self.slots); self.slots.append((m, t, lb, u))
                    self.row_lo.append(0.0); self.row_hi.append(0.0); r += 1
        self.R_E = r; self.row_lo.append(-INF); self.row_hi.append(1.0); r += 1
        self.R_T = list(range(r, r + 4)); self.row_lo += [-INF] * 4; self.row_hi += [1.0] * 4; r += 4
        self.R_G = list(range(r, r + 4)); self.row_lo += [-INF] * 4; self.row_hi += [0.0] * 4; r += 4
        # --- colonnes de rôles
        self.cost, self.lo, self.up = [], [], []
        self.cidx, self.cval = [], []  # listes par colonne
        self.fi, self.hi, self.yi, self.zi = {}, {}, {}, {}
        col = 0

        def addcol(c, lo, up, idx, val):
            nonlocal col
            self.cost.append(c); self.lo.append(lo); self.up.append(up); self.cidx.append(idx); self.cval.append(val)
            col += 1
            return col - 1
        for m in range(nm):
            e = inst.energy[m] / inst.cap
            gub = r; self.row_lo.append(-INF); self.row_hi.append(1.0); r += 1
            if self.ffeas[m]:
                idx = [self.R_E, gub] + [self.srow[(m, t)] for t, _, _ in inst.reqs[m]]
                val = [e, 1.0] + [-1.0] * len(inst.reqs[m])
                self.fi[m] = addcol(-inst.value[m], 0.0, 1.0, idx, val)
            # h : énergie, GUB, données totales lb/T par besoin ; z : -lb/T, +1 dans G_t ; z <= h ; z >= h si impossible
            hidx = [self.R_E, gub] + [self.R_T[t] for t, _, _ in inst.reqs[m]]
            hval = [e, 1.0] + [lb / self.T[t] for t, lb, _ in inst.reqs[m]]
            zrows = []
            for t, lb, u in inst.reqs[m]:
                rz = r; self.row_lo.append(-INF); self.row_hi.append(0.0); r += 1  # z - h <= 0
                zrows.append((t, lb, u, rz))
                hidx.append(rz); hval.append(-1.0)
                if lb > u:
                    rz2 = r; self.row_lo.append(-INF); self.row_hi.append(0.0); r += 1  # h - z <= 0
                    zrows[-1] = (t, lb, u, rz, rz2); hidx.append(rz2); hval.append(1.0)
            self.hi[m] = addcol(-(inst.value[m] // 2), 0.0, 1.0, hidx, hval)
            for zr in zrows:
                t, lb, u, rz = zr[:4]
                idx = [self.R_T[t], self.R_G[t], rz]; val = [-lb / self.T[t], 1.0, 1.0]
                if len(zr) == 5:
                    idx.append(zr[4]); val.append(-1.0)
                self.zi[(m, t)] = addcol(0.0, 0.0, 1.0, idx, val)
            if inst.gen_ok[m]:
                t, lb, _ = inst.reqs[m][0]
                self.yi[m] = addcol(0.0, 0.0, 1.0, [self.R_E, gub, self.R_T[t], self.R_G[t]], [e, 1.0, lb / self.T[t], -1.0])
        self.nrole = col
        self.nrow = r
        self.cols = []      # colonnes λ : (slot_index, tuple ids, size)
        self.colset = set()
        self.threads = threads
        self.verbose = verbose
        self.h = None

    def add_column(self, k, ids):
        key = (k, tuple(sorted(ids)))
        if key in self.colset:
            return False
        self.colset.add(key)
        m, t, lb, u = self.slots[k]
        size = sum(self.inst.ds[d][1] for d in ids)
        assert lb <= size <= u, (k, size, lb, u)
        idx = [self.drow[d] for d in ids] + [self.srow[(m, t)], self.R_T[t]]
        val = [1.0] * len(ids) + [1.0, size / self.T[t]]
        self.cost.append(0.0); self.lo.append(0.0); self.up.append(1.0); self.cidx.append(idx); self.cval.append(val)
        self.cols.append((k, key[1], size))
        if self.h is not None:
            self.h.addCol(0.0, 0.0, 1.0, len(idx), np.array(idx, dtype=np.int32), np.array(val, dtype=np.float64))
        return True

    def build(self, integer=False):
        import highspy as hp
        self.hp = hp
        h = hp.Highs()
        h.setOptionValue("output_flag", self.verbose)
        h.setOptionValue("threads", self.threads)
        lp = hp.HighsLp()
        n = len(self.cost)
        lp.num_col_ = n; lp.num_row_ = self.nrow
        lp.col_cost_ = np.array(self.cost); lp.col_lower_ = np.array(self.lo); lp.col_upper_ = np.array(self.up)
        lp.row_lower_ = np.array(self.row_lo); lp.row_upper_ = np.array(self.row_hi)
        starts = np.zeros(n + 1, dtype=np.int32)
        starts[1:] = np.cumsum([len(c) for c in self.cidx])
        lp.a_matrix_.format_ = hp.MatrixFormat.kColwise
        lp.a_matrix_.start_ = starts
        lp.a_matrix_.index_ = np.concatenate([np.array(c, dtype=np.int32) for c in self.cidx])
        lp.a_matrix_.value_ = np.concatenate([np.array(c, dtype=np.float64) for c in self.cval])
        if integer:
            lp.integrality_ = [hp.HighsVarType.kInteger] * n
        h.passModel(lp)
        return h

    def solve_lp(self, ipm=True):
        if self.h is None:
            self.h = self.build()
            if ipm:  # point intérieur sans crossover : duaux « centrés » (la CG stagne avec les duaux dégénérés du simplexe)
                self.h.setOptionValue("solver", "ipm"); self.h.setOptionValue("run_crossover", "off")
        self.h.run()
        s = self.h.getSolution()
        return np.array(s.col_value), np.array(s.row_dual), np.array(s.col_dual), self.h.getInfo().objective_function_value

    def lagr_bound(self, y):
        """Borne lagrangienne VALIDE (max) : lignes datasets/énergie/données/générateurs dualisées, structure par
        modèle (GUB, créneaux, z<=h) gardée et résolue exactement avec best_col_cost (pricing exact par DP)."""
        inst = self.inst
        tot = sum(y[self.drow[d]] for t in range(4) for s, d in self.free[t]) + y[self.R_E] + sum(y[self.R_T])
        for m in range(self.nm):
            e = inst.energy[m] / inst.cap
            opts = [0.0]
            if m in self.fi:
                c = -inst.value[m] - e * y[self.R_E]
                ok = True
                for t, lb, u in inst.reqs[m]:
                    bc = self.best_col_cost.get(self.kidx[(m, t)])
                    if bc is None or not np.isfinite(bc):
                        ok = False; break
                    c += bc
                if ok:
                    opts.append(c)
            c = -(inst.value[m] // 2) - e * y[self.R_E]
            for t, lb, u in inst.reqs[m]:
                c += -lb / self.T[t] * y[self.R_T[t]]
                zc = lb / self.T[t] * y[self.R_T[t]] - y[self.R_G[t]]
                c += zc if lb > u else min(0.0, zc)
            opts.append(c)
            if m in self.yi:
                t, lb, _ = inst.reqs[m][0]
                opts.append(-(e * y[self.R_E] + lb / self.T[t] * y[self.R_T[t]] - y[self.R_G[t]]))
            tot += min(opts)
        return -tot

    # ---------- pricing
    def price(self, y, cols_per_slot=2, eps=1e-6, narrow=40, force=False, extra=()):
        """y = duals des lignes (min). Retourne liste de (k, ids, rc) et la borne lagrangienne (max).
        force : une colonne pour chaque créneau quel que soit son rc (initialisation : y aléatoire)."""
        inst = self.inst
        new = []
        lag = 0.0
        self.best_col_cost = {}  # k -> min_S (g[S] + cT S) : coût (sans dual de créneau) de la meilleure colonne
        for t in range(4):
            items = self.free[t]
            ks = [k for k, (m, tt, lb, u) in enumerate(self.slots) if tt == t]
            if not ks:
                continue
            Smax = max(self.slots[k][3] for k in ks)
            n = len(items)
            g = np.full(Smax + 1, INF); g[0] = 0.0
            take = np.zeros((n, Smax + 1), dtype=bool)
            for i, (s, d) in enumerate(items):
                w = -y[self.drow[d]]
                if w < 0: w = 0.0
                cand = g[:Smax + 1 - s] + w
                tk = cand < g[s:]
                g[s:] = np.where(tk, cand, g[s:])
                take[i, s:] = tk
            cT = -y[self.R_T[t]] / self.T[t]
            S_all = np.arange(Smax + 1)
            val_all = g + cT * S_all
            for k in ks:
                m, tt, lb, u = self.slots[k]
                ck = -y[self.srow[(m, t)]] if not force else -1e12
                seg = val_all[lb:u + 1]
                j = int(np.argmin(seg))
                self.best_col_cost[k] = float(seg[j])
                rc = seg[j] + ck
                if rc < -eps:
                    lag += rc
                    S_list = [lb + j]
                    for off in extra:  # sommes supplémentaires (faible gaspillage) si atteignables
                        if lb + off <= u and np.isfinite(g[lb + off]) and lb + off not in S_list:
                            S_list.append(lb + off)
                    if cols_per_slot >= 2:
                        seg2 = seg[:narrow + 1]
                        j2 = int(np.argmin(seg2))
                        if seg2[j2] + ck < -eps and lb + j2 != lb + j:
                            S_list.append(lb + j2)
                    for S in S_list:
                        ids = []
                        cur = S
                        for i in range(n - 1, -1, -1):
                            if cur == 0:
                                break
                            if take[i, cur]:
                                ids.append(items[i][1]); cur -= items[i][0]
                        assert cur == 0
                        new.append((k, ids, rc))
            del take
        return new, lag


def packets_of_solution(inst, sol):
    """Rôles et paquets de la solution : f-créneaux -> ids de datasets libres."""
    src = {s for s, _ in sol["modelMappings"]}
    tg = {}
    for s, t in sol["modelMappings"]:
        tg.setdefault(t, []).append(inst.reqs[s][0][0])
    used = {}
    for d, m in sol["dataMappings"]:
        used.setdefault(m, []).append(d)
    roles = {"f": set(), "h": set(), "y": set(), "z": {}}
    pk = {}
    for m in set(used) | src | set(tg):
        if m in src:
            roles["y"].add(m)
        elif any(inst.ds[d][2] for d in used.get(m, [])) or m in tg:
            roles["h"].add(m); roles["z"][m] = tg.get(m, [])
        else:
            roles["f"].add(m)
            for d in used[m]:
                pk.setdefault((m, inst.ds[d][0]), []).append(d)
    return roles, pk


def realize(inst, M, x, exact=300):
    """Décode x (rôles + colonnes) en solution JSON : f par colonnes, h/y remplis avec copyrighté + libres restants."""
    nm = M.nm
    f = [m for m in range(nm) if m in M.fi and x[M.fi[m]] > 0.5]
    h = [m for m in range(nm) if x[M.hi[m]] > 0.5]
    y = [m for m in M.yi if x[M.yi[m]] > 0.5]
    z = {m: [t for t, _, _ in inst.reqs[m] if x[M.zi[(m, t)]] > 0.5] for m in h}
    pools = Pools(inst); pools.exact = exact
    dm = []
    usedd = set()
    for j, (k, ids, size) in enumerate(M.cols):
        if x[M.nrole + j] > 0.5:
            m, t, lb, u = M.slots[k]
            assert m in f, (m, k)
            for d in ids:
                assert d not in usedd; usedd.add(d); dm.append([d, m])
    for d in usedd:
        t, s, c = inst.ds[d]
        pools.remove(pools.p[t][c], (s, d))
    # générateurs d'abord (besoin unique, petit), puis h par fenêtre croissante
    ysrc = {t: [] for t in range(4)}
    dropped = set()
    for m in sorted(y, key=lambda m: inst.reqs[m][0][2] - inst.reqs[m][0][1]):
        t, lb, u = inst.reqs[m][0]
        tk = pools.fill(t, lb, u, [1, 0])
        if tk is None:
            dropped.add(m); continue
        for s, d, c in tk:
            dm.append([d, m])
        ysrc[t].append(m)
    mm = []
    hs = sorted(h, key=lambda m: min((u - lb for t, lb, u in inst.reqs[m] if t not in z[m]), default=10**9))
    for m in hs:
        need = [(t, lb, u) for t, lb, u in inst.reqs[m] if t not in z[m]]
        ok = all(len(ysrc[t]) > 0 for t in z[m])
        taken = []
        if ok:
            for t, lb, u in sorted(need, key=lambda r: r[2] - r[1]):
                tk = pools.fill(t, lb, u, [1, 0])
                if tk is None:
                    ok = False; break
                taken += tk
        if not ok:
            pools.undo(taken); dropped.add(m); continue
        for s, d, c in taken:
            dm.append([d, m])
        for t in z[m]:
            mm.append([ysrc[t].pop(), m])
    # générateurs non utilisés : on les retire (énergie)
    for t in range(4):
        for m in ysrc[t]:
            dropped.add(m)
    dm = [[d, m] for d, m in dm if m not in dropped]
    sol = {"dataMappings": dm, "modelMappings": mm}
    return sol, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("--start", default=None)
    ap.add_argument("--time-cg", type=float, default=600)
    ap.add_argument("--time-mip", type=float, default=900)
    ap.add_argument("--threads", type=int, default=12)
    ap.add_argument("--max-iter", type=int, default=100000)
    ap.add_argument("--cols-per-slot", type=int, default=2)
    ap.add_argument("--out", default=None)
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--target", type=float, default=None, help="objective_bound du MIP (valeur à atteindre)")
    ap.add_argument("--no-mip", action="store_true")
    ap.add_argument("--init-cols", type=int, default=3, help="colonnes initiales par créneau (prix aléatoires)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--rc-thr", type=float, default=None, help="candidats f : rc LP des rôles <= seuil (défaut : tous)")
    ap.add_argument("--noise", type=float, default=0.3)
    ap.add_argument("--extra", type=int, default=0, help="sommes supplémentaires par créneau et par tirage")
    ap.add_argument("--extra-max", type=int, default=30)
    ap.add_argument("--load-cols", nargs="*", default=None, help="fichiers .cols.json de colonnes à charger")
    ap.add_argument("--simplex", action="store_true", help="LP maître par simplexe (défaut : IPM sans crossover)")
    a = ap.parse_args()
    k = a.instance
    inst = Instance(k)
    start = a.start or os.path.join(ROOT, "best", f"instance_{k}.json")
    sol0 = json.load(open(start))
    v0, ok0, msg0 = evaluate(k, json.dumps(sol0))
    log(f"inst {k}: départ {start} = {v0} ({ok0} {msg0})")
    t0 = time.time()
    roles0, pk0 = packets_of_solution(inst, sol0)
    cand = None
    if a.rc_thr is not None:
        from m7_roles import Roles
        R = Roles(inst); lpr = R.solve(threads=a.threads)
        cand = set(roles0["f"]) | {m for m in range(len(inst.value)) if R.ub[R.fi[m]] > 0 and
                                    (lpr["x"][R.fi[m]] > 1e-9 or lpr["rc"][R.fi[m]] <= a.rc_thr)}
        log(f"candidats plein tarif (rc <= {a.rc_thr}) : {len(cand)} modèles (borne LP rôles {lpr['bound']:.1f})")
    M = Master(inst, threads=a.threads, cand=cand)
    nadd = 0
    for (m, t), ids in pk0.items():
        kk = [j for j, (mm_, tt, lb, u) in enumerate(M.slots) if mm_ == m and tt == t][0]
        nadd += M.add_column(kk, ids)
    log(f"maître : {M.nrow} lignes, {M.nrole} var. de rôles, {len(M.slots)} créneaux f, "
        f"{sum(len(v) for v in M.free)} datasets libres, {nadd} colonnes de best ({time.time()-t0:.1f}s)")
    # colonnes initiales pour TOUS les créneaux (sinon les duaux des créneaux sans colonne sont arbitraires
    # et le pricing ne converge pas) : K tirages de prix aléatoires sur les datasets
    rng = np.random.default_rng(a.seed)
    if a.load_cols:
        for fn in a.load_cols:
            P = json.load(open(fn))
            assert [tuple(x) for x in P["slots"]] == [tuple(x) for x in M.slots], "créneaux différents (même --rc-thr ?)"
            nadd = sum(M.add_column(kk, ids) for kk, ids, s_ in P["cols"])
            log(f"  chargé {fn}: +{nadd} colonnes ({len(M.cols)} au total)")
    for r_ in range(a.init_cols):
        yr = np.zeros(M.nrow)
        for t in range(4):
            for s_, d in M.free[t]:
                yr[M.drow[d]] = -(rng.uniform(1 - a.noise, 1 + a.noise) * s_ / 1000.0 + rng.uniform(0, a.noise))  # prix ~ taille, bruité
        extra = tuple(rng.integers(0, a.extra_max + 1, size=a.extra)) if a.extra else ()
        new, _ = M.price(yr, cols_per_slot=1, force=True, extra=extra)
        nadd = sum(M.add_column(kk, ids) for kk, ids, rc in new)
        if r_ % 5 == 0 or r_ == a.init_cols - 1:
            log(f"  init {r_}: +{nadd} colonnes ({len(M.cols)} au total, {time.time()-t0:.0f}s)")
    # hint vérifié : les rôles de best
    it = 0
    best_lag = INF
    while it < a.max_iter and time.time() - t0 < a.time_cg and a.time_cg > 0:
        x, y, rc_cols, obj = M.solve_lp(ipm=not a.simplex)
        # contrôle du signe des coûts réduits sur les colonnes existantes
        if it == 0 and len(M.cols) > 0:
            j = M.nrole
            mine = 0.0 - sum(y[i] * v for i, v in zip(M.cidx[j], M.cval[j]))
            log(f"  vérif rc colonne 0 : highs {rc_cols[j]:.6g} / calculé {mine:.6g}")
        new, lag = M.price(y, cols_per_slot=a.cols_per_slot)
        ub_lag = M.lagr_bound(y)  # borne lagrangienne valide (max)
        best_lag = min(best_lag, ub_lag)
        n_new = sum(M.add_column(kk, ids) for kk, ids, rc in new)
        log(f"it {it}: LP {-obj:.2f} | colonnes {len(M.cols)} (+{n_new}) | pricing min rc {min([r for _,_,r in new], default=0):.3f} "
            f"| borne lagrangienne {ub_lag:.2f} (meilleure {best_lag:.2f}) | {time.time()-t0:.0f}s")
        it += 1
        if n_new == 0:
            log("CG convergée : borne LP maître = %.3f" % (-obj)); best_lag = min(best_lag, -obj)
            break
    log(f"fin CG : {len(M.cols)} colonnes, meilleure borne {best_lag:.2f}, {time.time()-t0:.0f}s")
    if a.out:
        json.dump({"bound": best_lag, "ncols": len(M.cols), "cand": sorted(cand) if cand else None,
                   "slots": M.slots, "cols": [(kk, list(ids), s) for kk, ids, s in M.cols]},
                  open(a.out + ".cols.json", "w"))
    if a.no_mip:
        return
    # ---------- MIP
    hm = M.build(integer=True)
    hm.setOptionValue("time_limit", float(a.time_mip))
    hm.setOptionValue("mip_rel_gap", 0.0)
    hm.setOptionValue("output_flag", True)
    hm.setOptionValue("log_to_console", False)
    hm.setOptionValue("log_file", os.path.join(ROOT, "logs", f"m7_highs_{k}.log"))
    if a.target:
        hm.setOptionValue("objective_bound", -(a.target - 0.5))
    # hint
    x0 = np.zeros(len(M.cost))
    for m in roles0["f"]:
        x0[M.fi[m]] = 1
    for m in roles0["h"]:
        x0[M.hi[m]] = 1
        for t in roles0["z"].get(m, []):
            x0[M.zi[(m, t)]] = 1
    for m in roles0["y"]:
        x0[M.yi[m]] = 1
    for j, (kk, ids, s) in enumerate(M.cols):
        m, t, lb, u = M.slots[kk]
        if (m, t) in pk0 and tuple(sorted(pk0[(m, t)])) == ids:
            x0[M.nrole + j] = 1
    s0 = M.hp.HighsSolution(); s0.col_value = list(x0); hm.setSolution(s0)
    log(f"MIP : {len(M.cost)} colonnes, {M.nrow} lignes, hint valeur {-np.dot(M.cost, x0):.0f}, limite {a.time_mip}s")
    hm.run()
    info = hm.getInfo()
    st = hm.modelStatusToString(hm.getModelStatus())
    if not info.primal_solution_status:
        log(f"MIP : pas de solution ({st})"); return
    x = np.round(np.array(hm.getSolution().col_value))
    vm = -float(np.dot(M.cost, x))
    log(f"MIP : statut {st}, valeur maître {vm:.0f}, borne {-info.mip_dual_bound:.2f}, {time.time()-t0:.0f}s")
    sol, dropped = realize(inst, M, x)
    txt = json.dumps(sol)
    v, ok, msg = evaluate(k, txt)
    log(f"réalisation : {v} valide={ok} {msg} ; modèles abandonnés {len(dropped)}")
    if a.out:
        with open(a.out, "w") as f:
            f.write(txt)
    if a.save and ok:
        import subprocess
        subprocess.run([sys.executable, os.path.join(ROOT, "src", "save_if_better.py"), str(k), a.out or "/dev/stdin",
                        "--method", f"m7 CG+MIP cg={a.time_cg} mip={a.time_mip}"], input=None if a.out else txt.encode())


if __name__ == "__main__":
    main()
