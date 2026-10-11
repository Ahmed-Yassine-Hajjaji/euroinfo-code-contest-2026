#!/usr/bin/env python3
"""m9 — empaquetage d'abord, rôles LIBRES : colonnes « paquet exact → besoin » pour des modèles CANDIDATS
(support LP élargi), puis MIP HiGHS global (rôles f/h/y/z, dataset ≤ 1 fois, énergie, générateurs par type).

Colonnes :
  - pour chaque besoin (m, t) d'un modèle candidat (coût réduit LP ≥ -theta, + modèles de la solution de départ) :
    sous-ensembles de 1 / 2 / 3 datasets du bon type de somme dans [lb, min(ub, lb + eps_c)] (eps par cardinalité),
    énumérés dans le pool LIBRE (utilisables plein tarif) et, si --hcols > 0, dans le pool complet (demi-tarif) ;
    k_c meilleurs (excès minimal) parmi `cap` trouvés en ordre aléatoire ;
  - pour chaque générateur candidat (mono-modèle, coût réduit ≥ -theta, + générateurs de la solution) : idem, pool complet ;
  - paquets de la solution de départ et des solutions --extra : vers leur créneau d'origine + kcur besoins compatibles
    de meilleur coût réduit (comme rematch) ;
  - --cross K : chaque paquet généré est aussi proposé à K autres besoins compatibles (lb ≤ S ≤ ub) de meilleur coût réduit.
Objectif = score du concours (Σ v f + Σ v//2 h). Hint = solution de départ. Décodage → JSON validé par le scoreur.

Usage : python src/m9_mip.py 6 [--start best/instance_6.json] [--extra f1 f2 ...] --theta 10 --k1 20 --k2 20 --k3 20
        --eps1 500 --eps2 10 --eps3 2 --hcols 5 --kcur 10 --cross 0 --time 1200 --threads 1 --seed 0 --tag x [--save] [--lp-only]
"""
import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402
from rematch import reduced_costs, candidate_models  # noqa: E402

try:
    from numba import njit
except Exception:  # pragma: no cover
    def njit(*a, **k):
        def w(f):
            return f
        return w if not (a and callable(a[0])) else a[0]


@njit(cache=True)
def _enum3(sz, lb, hi1, hi2, hi3, cap2, cap3, order, order2):
    """Sous-ensembles de 1..3 indices de `sz` (trié croissant) : singletons de somme dans [lb, hi1] (tous),
    paires dans [lb, hi2] (cap2 au plus, premiers éléments dans l'ordre `order`), triplets dans [lb, hi3]
    (cap3 au plus, i dans l'ordre `order`, j dans l'ordre `order2`). Retourne (ia, ib, ic, somme)."""
    n = sz.shape[0]
    tot = n + cap2 + cap3 + 4
    oa = np.empty(tot, np.int32); ob = np.empty(tot, np.int32); oc = np.empty(tot, np.int32); os_ = np.empty(tot, np.int64)
    m = 0
    for i in range(n):
        if sz[i] > hi1:
            break
        if sz[i] >= lb:
            oa[m] = i; ob[m] = -1; oc[m] = -1; os_[m] = sz[i]; m += 1
    cnt = 0
    if cap2 > 0:
        for oi in range(n):
            i = order[oi]
            if cnt >= cap2:
                break
            lo_ = lb - sz[i]; hi_ = hi2 - sz[i]
            if hi_ < sz[i]:
                continue
            a = np.searchsorted(sz, lo_)
            b = np.searchsorted(sz, hi_, side='right')
            if a <= i:
                a = i + 1
            for j in range(a, b):
                if cnt >= cap2:
                    break
                oa[m] = i; ob[m] = j; oc[m] = -1; os_[m] = sz[i] + sz[j]; m += 1; cnt += 1
    cnt = 0
    if cap3 > 0:
        for oi in range(n):
            i = order[oi]
            if cnt >= cap3:
                break
            if sz[i] * 3 > hi3:
                continue
            for oj in range(n):
                j = order2[oj]
                if j <= i:
                    continue
                if cnt >= cap3:
                    break
                s2 = sz[i] + sz[j]
                lo_ = lb - s2; hi_ = hi3 - s2
                if hi_ < sz[j]:
                    continue
                a = np.searchsorted(sz, lo_)
                b = np.searchsorted(sz, hi_, side='right')
                if a <= j:
                    a = j + 1
                for k in range(a, b):
                    if cnt >= cap3:
                        break
                    oa[m] = i; ob[m] = j; oc[m] = k; os_[m] = s2 + sz[k]; m += 1; cnt += 1
    return oa[:m], ob[:m], oc[:m], os_[:m]


def enum_window(sz, ids, lb, ub, eps, ks, rng, capmul=3):
    """Paquets (tuple ids, somme) pour la fenêtre [lb, ub] dans le pool (sz trié, ids), eps/ks par cardinalité."""
    n = len(sz)
    if n == 0:
        return []
    hi1 = min(ub, lb + eps[0]); hi2 = min(ub, lb + eps[1]); hi3 = min(ub, lb + eps[2])
    order = np.array(rng.permutation(n), np.int64); order2 = np.array(rng.permutation(n), np.int64)
    ia, ib, ic, ss = _enum3(sz, lb, hi1, hi2, hi3, ks[1] * capmul, ks[2] * capmul, order, order2)
    groups = [[], [], []]
    for a, b, c, s in zip(ia.tolist(), ib.tolist(), ic.tolist(), ss.tolist()):
        card = 1 + (b >= 0) + (c >= 0)
        groups[card - 1].append((s, a, b, c))
    out = []
    for card in range(3):
        g = groups[card]
        if len(g) > ks[card]:
            rng.shuffle(g)
            g.sort(key=lambda x: x[0])
            g = g[:ks[card]]
        for s, a, b, c in g:
            out.append((tuple(sorted(int(ids[x]) for x in (a, b, c) if x >= 0)), s))
    return out


def packs_of_solution(inst, sol):
    """{(m, t): [datasets]} et ensembles sources/cibles."""
    pk = {}
    for d, m in sol["dataMappings"]:
        pk.setdefault((m, inst.ds[d][0]), []).append(d)
    src = {s for s, _ in sol["modelMappings"]}
    cov = {(t, inst.reqs[s][0][0]) for s, t in sol["modelMappings"]}
    return pk, src, cov


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("--start", default=None)
    ap.add_argument("--extra", nargs="*", default=[])
    ap.add_argument("--theta", type=float, default=10.0)
    ap.add_argument("--theta-gen", type=float, default=None)
    ap.add_argument("--k1", type=int, default=20); ap.add_argument("--k2", type=int, default=20); ap.add_argument("--k3", type=int, default=20)
    ap.add_argument("--eps1", type=int, default=500); ap.add_argument("--eps2", type=int, default=10); ap.add_argument("--eps3", type=int, default=2)
    ap.add_argument("--hcols", type=float, default=0.25, help="fraction des k pour les colonnes demi-tarif (pool complet) des modèles")
    ap.add_argument("--kcur", type=int, default=10, help="besoins compatibles par paquet des solutions de départ (coût réduit)")
    ap.add_argument("--cross", type=int, default=0, help="autres besoins compatibles par paquet généré")
    ap.add_argument("--time", type=float, default=1200)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tag", default="x")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--lp-only", action="store_true")
    ap.add_argument("--gap", type=float, default=0.0)
    ap.add_argument("--max-cols", type=int, default=900000)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--fix-gen", action="store_true", help="générateurs et leurs paquets figés comme dans la solution de départ")
    ap.add_argument("--lp-solver", default="choose", help="simplex / ipm / pdlp (mode --lp-only)")
    a = ap.parse_args()
    t0 = time.time()
    k = a.instance
    inst = Instance(k)
    nm = len(inst.value)
    rng = np.random.RandomState(a.seed)
    start = a.start or os.path.join(ROOT, "best", f"instance_{k}.json")
    sol = json.load(open(start))
    lp = json.load(open(os.path.join(ROOT, "runs", f"lp_{k}.json")))
    rcm, rcg = reduced_costs(inst, lp)
    M, G = candidate_models(inst, lp, a.theta)
    if a.theta_gen is not None:
        G = {g for g in range(nm) if inst.gen_ok[g] and rcg[g] >= -a.theta_gen}
    pk0, src0, cov0 = packs_of_solution(inst, sol)
    for (m, t) in pk0:
        (G if m in src0 else M).add(m)
    for _, m in sol["modelMappings"]:
        M.add(m)
    extras = []
    for fn in a.extra:
        try:
            so = json.load(open(fn))
        except Exception as e:
            print(f"  extra {fn} ignoré : {e!r}", flush=True); continue
        pk2, src2, _ = packs_of_solution(inst, so)
        extras.append((pk2, src2))
        for (m, t) in pk2:
            (G if m in src2 else M).add(m)
    print(f"inst {k} départ {start} : {len(M)} modèles candidats, {len(G)} générateurs candidats (theta {a.theta}), "
          f"{len(extras)} solutions extra", flush=True)
    # pools
    pools = {}
    for t in range(4):
        for cr in (0, 1):
            lst = sorted((s, d) for d, (tt, s, c) in enumerate(inst.ds) if tt == t and (cr or not c))
            pools[(t, cr)] = (np.array([s for s, _ in lst], np.int64), np.array([d for _, d in lst], np.int64))
    # --- génération des paquets ---
    packs = {}      # key -> pid
    plist = []      # pid -> (t, S, free, key)
    cols = []       # (pid, kind, target)  kind 0 : besoin (m, t) ; kind 1 : générateur g
    colset = set()

    def pid_of(key):
        p = packs.get(key)
        if p is None:
            p = len(plist); packs[key] = p
            t = inst.ds[key[0]][0]
            plist.append((t, sum(inst.ds[d][1] for d in key), not any(inst.ds[d][2] for d in key), key))
        return p

    def add_col(pid, kind, tgt):
        kk = (pid, kind, tgt)
        if kk not in colset:
            colset.add(kk); cols.append(kk)

    eps = (a.eps1, a.eps2, a.eps3)
    ks = (a.k1, a.k2, a.k3)
    ksh = tuple(max(1, int(round(x * a.hcols))) for x in ks) if a.hcols > 0 else (0, 0, 0)
    stat = {"win_f": 0, "win_h": 0, "win_g": 0, "gen_cols": 0}
    t1 = time.time()
    for m in sorted(M):
        for t, lb, ub in inst.reqs[m]:
            if lb > ub:
                continue
            sz, ids = pools[(t, 0)]
            for key, S in enum_window(sz, ids, lb, ub, eps, ks, rng):
                add_col(pid_of(key), 0, (m, t)); stat["gen_cols"] += 1
            stat["win_f"] += 1
            if a.hcols > 0:
                sz, ids = pools[(t, 1)]
                for key, S in enum_window(sz, ids, lb, ub, eps, ksh, rng):
                    add_col(pid_of(key), 0, (m, t)); stat["gen_cols"] += 1
                stat["win_h"] += 1
    for g in sorted(G):
        if a.fix_gen:
            break
        t, lb, ub = inst.reqs[g][0]
        sz, ids = pools[(t, 1)]
        for key, S in enum_window(sz, ids, lb, ub, eps, ks, rng):
            add_col(pid_of(key), 1, g); stat["gen_cols"] += 1
        stat["win_g"] += 1
    ngen_packs = len(plist)
    print(f"  génération : {stat}, {ngen_packs} paquets distincts, {len(cols)} colonnes, {time.time() - t1:.0f}s", flush=True)
    # tables besoins / générateurs par type pour les affectations croisées
    needs = [[] for _ in range(4)]
    for m in M:
        for t, lb, ub in inst.reqs[m]:
            if lb <= ub:
                needs[t].append((lb, ub, m))
    gens = [[] for _ in range(4)]
    for g in G:
        t, lb, ub = inst.reqs[g][0]
        gens[t].append((lb, ub, g))
    NT = []
    for t in range(4):
        L = np.array([x[0] for x in needs[t]], np.int64); U = np.array([x[1] for x in needs[t]], np.int64)
        Mn = np.array([x[2] for x in needs[t]], np.int64); RC = np.array([rcm[m] for m in Mn], float)
        Lg = np.array([x[0] for x in gens[t]], np.int64); Ug = np.array([x[1] for x in gens[t]], np.int64)
        Gg = np.array([x[2] for x in gens[t]], np.int64); RCg = np.array([rcg[g] for g in Gg], float)
        NT.append((L, U, Mn, RC, Lg, Ug, Gg, RCg))

    def cross_attach(pid, K, kinds=(0, 1)):
        t, S, free, key = plist[pid]
        L, U, Mn, RC, Lg, Ug, Gg, RCg = NT[t]
        if 0 in kinds and len(L):
            js = np.nonzero((L <= S) & (S <= U))[0]
            if len(js) > K:
                js = js[np.argsort(-RC[js])[:K]]
            for j in js:
                add_col(pid, 0, (int(Mn[j]), t))
        if 1 in kinds and len(Lg):
            js = np.nonzero((Lg <= S) & (S <= Ug))[0]
            if len(js) > K:
                js = js[np.argsort(-RCg[js])[:K]]
            for j in js:
                add_col(pid, 1, int(Gg[j]))

    # paquets des solutions de départ / extra : créneau d'origine + kcur compatibles
    hint_cols = set()
    for pk, src in [(pk0, src0)] + extras:
        for (m, t), ds in pk.items():
            pid = pid_of(tuple(sorted(ds)))
            if m in src:
                add_col(pid, 1, m)
                if pk is pk0: hint_cols.add((pid, 1, m))
            else:
                add_col(pid, 0, (m, t))
                if pk is pk0: hint_cols.add((pid, 0, (m, t)))
            if a.kcur > 0:
                cross_attach(pid, a.kcur, kinds=(0,) if a.fix_gen else (0, 1))
    if a.cross > 0:
        for pid in range(ngen_packs):
            cross_attach(pid, a.cross)
    print(f"  colonnes totales {len(cols)} ({len(plist)} paquets) ; construction {time.time() - t0:.0f}s", flush=True)
    if len(cols) > a.max_cols:
        print(f"  trop de colonnes (> {a.max_cols}) : abandon", flush=True); sys.exit(3)
    # --- modèle HiGHS ---
    obj, lo, hi = [], [], []
    col = 0
    fi, hi_, yi, zi = {}, {}, {}, {}

    def newvar(c, u=1.0):
        nonlocal col
        obj.append(c); lo.append(0.0); hi.append(u); col += 1
        return col - 1

    for m in sorted(M):
        feas = all(lb <= ub for _, lb, ub in inst.reqs[m])
        fi[m] = newvar(-inst.value[m], 1.0 if feas else 0.0)
        hi_[m] = newvar(-(inst.value[m] // 2))
        for t, lb, ub in inst.reqs[m]:
            zi[(m, t)] = newvar(0.0)
    for g in sorted(G):
        yi[g] = newvar(0.0)
    nrole = col
    rows, rcols, vals, rlo, rhi = [], [], [], [], []
    r = 0
    R1 = {}
    for m in sorted(M | G):
        R1[m] = r; rlo.append(-np.inf); rhi.append(1.0)
        if m in fi:
            rows += [r, r]; rcols += [fi[m], hi_[m]]; vals += [1, 1]
        if m in yi:
            rows.append(r); rcols.append(yi[m]); vals.append(1)
        r += 1
    R2, R3 = {}, {}
    for m in sorted(M):
        for t, lb, ub in inst.reqs[m]:
            R2[(m, t)] = r; rlo.append(0.0); rhi.append(0.0)
            rows += [r, r, r]; rcols += [zi[(m, t)], fi[m], hi_[m]]; vals += [1, -1, -1]; r += 1
            R3[(m, t)] = r; rlo.append(-np.inf); rhi.append(0.0)
            rows += [r, r]; rcols += [zi[(m, t)], hi_[m]]; vals += [1, -1]; r += 1
    R4 = {}
    for g in sorted(G):
        R4[g] = r; rlo.append(0.0); rhi.append(0.0)
        rows.append(r); rcols.append(yi[g]); vals.append(-1); r += 1
    R5 = list(range(r, r + 4)); r += 4
    rlo += [-np.inf] * 4; rhi += [0.0] * 4
    for (m, t), c in zi.items():
        rows.append(R5[t]); rcols.append(c); vals.append(1)
    for g, c in yi.items():
        rows.append(R5[inst.reqs[g][0][0]]); rcols.append(c); vals.append(-1)
    RD = list(range(r, r + len(inst.ds))); r += len(inst.ds)
    rlo += [-np.inf] * len(inst.ds); rhi += [1.0] * len(inst.ds)
    RE = r; r += 1; rlo.append(-np.inf); rhi.append((inst.cap - 1e6) * 1e-9)
    for m in M:
        rows += [RE, RE]; rcols += [fi[m], hi_[m]]; vals += [inst.energy[m] * 1e-9] * 2
    for g in G:
        rows.append(RE); rcols.append(yi[g]); vals.append(inst.energy[g] * 1e-9)
    acol = []
    for (pid, kind, tgt) in cols:
        t, S, free, key = plist[pid]
        c = newvar(0.0)
        acol.append((c, pid, kind, tgt))
        if kind == 0:
            rows.append(R2[tgt]); rcols.append(c); vals.append(1)
            if not free:
                rows.append(R3[tgt]); rcols.append(c); vals.append(1)
        else:
            rows.append(R4[tgt]); rcols.append(c); vals.append(1)
        for d in key:
            rows.append(RD[d]); rcols.append(c); vals.append(1)
    from scipy.sparse import coo_matrix
    A = coo_matrix((np.array(vals, float), (np.array(rows), np.array(rcols))), shape=(r, col)).tocsc()
    print(f"  modèle : {col} colonnes ({nrole} rôles, {len(acol)} affectations), {r} lignes, {A.nnz} nz, {time.time() - t0:.0f}s", flush=True)
    # hint
    trained = {m for (m, t) in pk0 if m not in src0} | {t for _, t in sol["modelMappings"]}
    defiled = {m: (any(inst.ds[d][2] for (mm, t), ds in pk0.items() if mm == m for d in ds)
                   or any((m, t) in cov0 for t in range(4))) for m in trained}
    x0 = np.zeros(col)
    for m in trained:
        x0[hi_[m] if defiled[m] else fi[m]] = 1.0
        for t, _, _ in inst.reqs[m]:
            if (m, t) in cov0:
                x0[zi[(m, t)]] = 1.0
    for g in src0:
        x0[yi[g]] = 1.0
    nh = 0
    for c, pid, kind, tgt in acol:
        if (pid, kind, tgt) in hint_cols:
            x0[c] = 1.0; nh += 1
    if a.fix_gen:  # générateurs figés : y_g et leurs colonnes de paquets fixés à la valeur du hint
        for g in G:
            lo[yi[g]] = hi[yi[g]] = x0[yi[g]]
        for c, pid, kind, tgt in acol:
            if kind == 1:
                lo[c] = hi[c] = x0[c]
    Ax = A @ x0
    bad = np.nonzero((Ax > np.array(rhi) + 1e-9) | (Ax < np.array(rlo) - 1e-9))[0]
    print(f"  hint : {nh} affectations, valeur {-float(np.dot(obj, x0)):.0f}, lignes violées {len(bad)}", flush=True)
    import highspy
    h = highspy.Highs()
    h.setOptionValue("output_flag", True)
    h.setOptionValue("log_to_console", True)
    h.setOptionValue("threads", int(a.threads))
    h.setOptionValue("random_seed", int(a.seed))
    lpm = highspy.HighsLp()
    lpm.num_col_ = col; lpm.num_row_ = r
    lpm.col_cost_ = np.array(obj, float); lpm.col_lower_ = np.array(lo); lpm.col_upper_ = np.array(hi)
    lpm.row_lower_ = np.array(rlo); lpm.row_upper_ = np.array(rhi)
    lpm.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    lpm.a_matrix_.start_ = A.indptr.astype(np.int32); lpm.a_matrix_.index_ = A.indices.astype(np.int32); lpm.a_matrix_.value_ = A.data
    if not a.lp_only:
        lpm.integrality_ = [highspy.HighsVarType.kInteger] * col
    h.passModel(lpm)
    h.setOptionValue("time_limit", float(a.time))
    h.setOptionValue("mip_rel_gap", float(a.gap))
    if a.lp_only:
        h.setOptionValue("solver", a.lp_solver)
        h.setOptionValue("run_crossover", "off")
        h.run()
        print(f"  LP : {-h.getInfo().objective_function_value:.1f} ({time.time() - t0:.0f}s) {h.modelStatusToString(h.getModelStatus())}", flush=True)
        return
    s0 = highspy.HighsSolution(); s0.col_value = list(x0); h.setSolution(s0)
    h.run()
    info = h.getInfo()
    xs = np.array(h.getSolution().col_value)
    if len(xs) != col or info.primal_solution_status == 0:
        print(f"  HiGHS : pas de solution ({h.modelStatusToString(h.getModelStatus())})", flush=True); sys.exit(4)
    x = np.round(xs)
    val = -float(np.dot(obj, x)); bound = -float(info.mip_dual_bound) if info.mip_dual_bound else None
    print(f"  MIP : valeur {val:.0f} borne {bound} ({time.time() - t0:.0f}s) {h.modelStatusToString(h.getModelStatus())}", flush=True)
    # décodage
    dm, mm = [], []
    ysel = {g for g in G if x[yi[g]] > 0.5}
    for c, pid, kind, tgt in acol:
        if x[c] > 0.5:
            m = tgt[0] if kind == 0 else tgt
            dm.extend([int(d), int(m)] for d in plist[pid][3])
    for t in range(4):
        gl = [g for g in sorted(ysel) if inst.reqs[g][0][0] == t]
        tl = [m for (m, tt) in sorted(zi) if tt == t and x[zi[(m, tt)]] > 0.5]
        if len(tl) > len(gl):
            print(f"  ATTENTION type {t} : {len(tl)} cibles > {len(gl)} générateurs", flush=True)
        for g, m in zip(gl, tl):
            mm.append([int(g), int(m)])
        drop = set(gl[len(tl):])
        if drop:
            dm = [[d, m_] for d, m_ in dm if m_ not in drop]
    out = {"dataMappings": dm, "modelMappings": mm}
    txt = json.dumps(out, separators=(",", ":"))
    outf = os.path.join(ROOT, "runs", f"m9_{a.tag}.json")
    with open(outf, "w") as f:
        f.write(txt)
    from save_if_better import evaluate, save_if_better
    sc, ok, msg = evaluate(k, txt, inst.txt)
    print(f"  score officiel {sc} valide={ok} {msg} ; écrit {outf} ; total {time.time() - t0:.0f}s", flush=True)
    if a.save and ok:
        save_if_better(k, txt, method=f"m9 {a.tag} theta={a.theta} k={ks} eps={eps} seed={a.seed}", dataset_txt=inst.txt)


if __name__ == "__main__":
    main()
