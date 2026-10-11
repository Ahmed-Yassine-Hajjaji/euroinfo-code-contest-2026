#!/usr/bin/env python3
"""m9_rins — plongeon guidé par le LP (RINS) sur le modèle à colonnes m9 (instance 6).

1. Construit le même modèle que m9_mip.py (colonnes « paquet exact → besoin », rôles f/h/y/z ; fonctions importées,
   m9_mip.py n'est pas modifié) et résout la LP racine (IPM HiGHS par défaut, cache runs/m9_rins_lp_<hash>.npz).
2. Fixe à 1 : (a) les colonnes de valeur LP >= seuil ; (b) les colonnes du support LP (> 0) présentes dans la solution
   courante (best/). Cohérence : dataset <= 1 fois, besoin <= 1 colonne, générateur <= 1 colonne (on garde la plus
   grande valeur LP), énergie des rôles impliqués <= cap. Option : fraction aléatoire des candidats, colonnes de coût
   réduit très défavorable fixées à 0, ligne de coupure objectif >= courant + 1.
3. Résout le MIP réduit (HiGHS, tranche courte, hint = courant) ; toute solution décodée passe par save_if_better.
   Si infaisable / sans gain : seuil suivant, autre graine.

Usage : python src/m9_rins.py 6 [--start best/instance_6.json] [params de génération de m9_mip] \
        --thresholds 0.95,0.9,0.8 --frac 1.0 --slice 300 --total 3000 --threads 1 --lp-solver ipm --tag x --save
"""
import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402
from rematch import reduced_costs, candidate_models  # noqa: E402
from m9_mip import enum_window, packs_of_solution  # noqa: E402

LOG0 = time.time()


def log(msg):
    print(f"[{time.time() - LOG0:6.0f}s] {msg}", flush=True)


# ----------------------------------------------------------------------------------------------------------------------
# construction du modèle (copie fidèle de m9_mip.main, retourne les structures au lieu de résoudre)
# ----------------------------------------------------------------------------------------------------------------------
def build_model(a, inst, sol, rng):
    k = a.instance
    nm = len(inst.value)
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
            log(f"  extra {fn} ignoré : {e!r}"); continue
        pk2, src2, _ = packs_of_solution(inst, so)
        extras.append((pk2, src2))
        for (m, t) in pk2:
            (G if m in src2 else M).add(m)
    log(f"inst {k} : {len(M)} modèles candidats, {len(G)} générateurs candidats (theta {a.theta}), {len(extras)} extra")
    pools = {}
    for t in range(4):
        for cr in (0, 1):
            lst = sorted((s, d) for d, (tt, s, c) in enumerate(inst.ds) if tt == t and (cr or not c))
            pools[(t, cr)] = (np.array([s for s, _ in lst], np.int64), np.array([d for _, d in lst], np.int64))
    packs = {}; plist = []; cols = []; colset = set()

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
    t1 = time.time()
    for m in sorted(M):
        for t, lb, ub in inst.reqs[m]:
            if lb > ub:
                continue
            sz, ids = pools[(t, 0)]
            for key, S in enum_window(sz, ids, lb, ub, eps, ks, rng):
                add_col(pid_of(key), 0, (m, t))
            if a.hcols > 0:
                sz, ids = pools[(t, 1)]
                for key, S in enum_window(sz, ids, lb, ub, eps, ksh, rng):
                    add_col(pid_of(key), 0, (m, t))
    for g in sorted(G):
        if a.fix_gen:
            break
        t, lb, ub = inst.reqs[g][0]
        sz, ids = pools[(t, 1)]
        for key, S in enum_window(sz, ids, lb, ub, eps, ks, rng):
            add_col(pid_of(key), 1, g)
    ngen_packs = len(plist)
    log(f"  génération : {ngen_packs} paquets, {len(cols)} colonnes, {time.time() - t1:.0f}s")
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

    for pk, src in [(pk0, src0)] + extras:
        for (m, t), ds in pk.items():
            pid = pid_of(tuple(sorted(ds)))
            if m in src:
                add_col(pid, 1, m)
            else:
                add_col(pid, 0, (m, t))
            if a.kcur > 0:
                cross_attach(pid, a.kcur, kinds=(0,) if a.fix_gen else (0, 1))
    if a.cross > 0:
        for pid in range(ngen_packs):
            cross_attach(pid, a.cross)
    log(f"  colonnes totales {len(cols)} ({len(plist)} paquets)")
    if len(cols) > a.max_cols:
        log(f"  trop de colonnes (> {a.max_cols}) : abandon"); sys.exit(3)
    # --- matrice ---
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
    for m in sorted(M | G):
        rlo.append(-np.inf); rhi.append(1.0)
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
    # ligne de coupure (objectif) : Σ obj x <= rhs ; bornes changées par tour (inactive = +inf)
    RC = r; r += 1; rlo.append(-np.inf); rhi.append(np.inf)
    for j in range(nrole):
        if obj[j] != 0.0:
            rows.append(RC); rcols.append(j); vals.append(obj[j])
    from scipy.sparse import coo_matrix
    A = coo_matrix((np.array(vals, float), (np.array(rows), np.array(rcols))), shape=(r, col)).tocsc()
    log(f"  modèle : {col} colonnes ({nrole} rôles, {len(acol)} affectations), {r} lignes, {A.nnz} nz")
    return dict(M=M, G=G, obj=np.array(obj, float), lo=np.array(lo, float), hi=np.array(hi, float), A=A,
                rlo=np.array(rlo, float), rhi=np.array(rhi, float), nrole=nrole, acol=acol, plist=plist, cols=cols,
                fi=fi, hi_=hi_, yi=yi, zi=zi, RC=RC, ncol=col, nrow=r)


def hint_vector(mdl, inst, sol):
    """x0 (0/1) pour une solution JSON : rôles + colonnes de paquets présentes dans le modèle."""
    pk0, src0, cov0 = packs_of_solution(inst, sol)
    fi, hi_, yi, zi = mdl["fi"], mdl["hi_"], mdl["yi"], mdl["zi"]
    trained = {m for (m, t) in pk0 if m not in src0} | {t for _, t in sol["modelMappings"]}
    defiled = {m: (any(inst.ds[d][2] for (mm, t), ds in pk0.items() if mm == m for d in ds)
                   or any((m, t) in cov0 for t in range(4))) for m in trained}
    x0 = np.zeros(mdl["ncol"])
    miss = 0
    for m in trained:
        if m not in fi:
            miss += 1; continue
        x0[hi_[m] if defiled[m] else fi[m]] = 1.0
        for t, _, _ in inst.reqs[m]:
            if (m, t) in cov0 and (m, t) in zi:
                x0[zi[(m, t)]] = 1.0
    for g in src0:
        if g in yi:
            x0[yi[g]] = 1.0
        else:
            miss += 1
    want = set()
    for (m, t), ds in pk0.items():
        key = tuple(sorted(ds))
        want.add((key, 1, m) if m in src0 else (key, 0, (m, t)))
    nh = 0
    for c, pid, kind, tgt in mdl["acol"]:
        if (mdl["plist"][pid][3], kind, tgt) in want:
            x0[c] = 1.0; nh += 1
    return x0, nh, len(want) - nh + miss


def decode(mdl, inst, x):
    acol, plist, G, yi, zi = mdl["acol"], mdl["plist"], mdl["G"], mdl["yi"], mdl["zi"]
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
            log(f"  ATTENTION type {t} : {len(tl)} cibles > {len(gl)} générateurs")
        for g, m in zip(gl, tl):
            mm.append([int(g), int(m)])
        drop = set(gl[len(tl):])
        if drop:
            dm = [[d, m_] for d, m_ in dm if m_ not in drop]
    return {"dataMappings": dm, "modelMappings": mm}


def model_hash(mdl):
    h = hashlib.md5()
    h.update(mdl["obj"].tobytes()); h.update(mdl["lo"].tobytes()); h.update(mdl["hi"].tobytes())
    h.update(mdl["A"].indptr.tobytes()); h.update(mdl["A"].indices.tobytes()); h.update(mdl["rhi"].tobytes())
    return h.hexdigest()[:12]


def new_highs(a, threads, seed):
    import highspy
    h = highspy.Highs()
    h.setOptionValue("output_flag", bool(a.verbose))
    h.setOptionValue("log_to_console", bool(a.verbose))
    h.setOptionValue("threads", int(threads))
    h.setOptionValue("random_seed", int(seed))
    return h


def pass_model(h, mdl, lo, hi, rhi, integral):
    import highspy
    lpm = highspy.HighsLp()
    lpm.num_col_ = mdl["ncol"]; lpm.num_row_ = mdl["nrow"]
    lpm.col_cost_ = mdl["obj"]; lpm.col_lower_ = lo; lpm.col_upper_ = hi
    lpm.row_lower_ = mdl["rlo"]; lpm.row_upper_ = rhi
    lpm.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    A = mdl["A"]
    lpm.a_matrix_.start_ = A.indptr.astype(np.int32); lpm.a_matrix_.index_ = A.indices.astype(np.int32); lpm.a_matrix_.value_ = A.data
    if integral:
        lpm.integrality_ = [highspy.HighsVarType.kInteger] * mdl["ncol"]
    h.passModel(lpm)


def solve_lp(a, mdl, x0):
    """LP racine (cache npz par hash du modèle). Retourne (x_lp, rc_lp, borne)."""
    hsh = model_hash(mdl)
    fn = os.path.join(ROOT, "runs", f"m9_rins_lp_{hsh}.npz")
    if os.path.exists(fn) and not a.lp_recompute:
        z = np.load(fn)
        if len(z["x"]) == mdl["ncol"]:
            log(f"  LP : cache {fn} (borne {float(z['bound']):.1f})")
            return z["x"], z["rc"], float(z["bound"])
    h = new_highs(a, a.lp_threads, a.seed)
    h.setOptionValue("solver", a.lp_solver)
    h.setOptionValue("run_crossover", "on" if a.crossover else "off")
    h.setOptionValue("time_limit", float(a.lp_time))
    pass_model(h, mdl, mdl["lo"], mdl["hi"], mdl["rhi"], False)
    t1 = time.time()
    h.run()
    st = h.modelStatusToString(h.getModelStatus())
    s = h.getSolution()
    x = np.array(s.col_value); rc = np.array(s.col_dual) if len(s.col_dual) == mdl["ncol"] else np.zeros(mdl["ncol"])
    bound = -float(h.getInfo().objective_function_value)
    log(f"  LP ({a.lp_solver}, crossover {a.crossover}) : {bound:.1f} en {time.time() - t1:.0f}s, {st} ; "
        f"colonnes >0.999 : {int(np.sum(x[mdl['nrole']:] > 0.999))}, >0.9 : {int(np.sum(x[mdl['nrole']:] > 0.9))}, "
        f">0.5 : {int(np.sum(x[mdl['nrole']:] > 0.5))}, >1e-6 : {int(np.sum(x[mdl['nrole']:] > 1e-6))}")
    if len(x) != mdl["ncol"] or "ptimal" not in st and "imit" not in st:
        log("  LP non résolue : abandon"); sys.exit(5)
    np.savez_compressed(fn, x=x, rc=rc, bound=bound, hash=hsh)
    log(f"  LP sauvée dans {fn}")
    return x, rc, bound


def choose_fixed(a, mdl, inst, x_lp, x0, thr, frac, rng):
    """Colonnes à fixer à 1 : (a) x_lp >= thr ; (b) x_lp > 0 et x0 == 1. Cohérence dataset / besoin / générateur / énergie."""
    nrole = mdl["nrole"]; acol = mdl["acol"]; plist = mdl["plist"]
    xa = x_lp[nrole:]; xb = x0[nrole:]
    ca = set(np.nonzero(xa >= thr)[0].tolist())
    cb = set(np.nonzero((xa > a.support_eps) & (xb > 0.5))[0].tolist())
    cand = sorted(ca | cb, key=lambda j: -xa[j])
    if frac < 1.0:
        keep = rng.random_sample(len(cand)) < frac
        cand = [j for j, kp in zip(cand, keep) if kp]
    used_d, used_need, used_gen, used_model = set(), set(), set(), {}
    fixed = []; conflicts = 0
    for j in cand:
        c, pid, kind, tgt = acol[j]
        t, S, free, key = plist[pid]
        if any(d in used_d for d in key):
            conflicts += 1; continue
        m = tgt[0] if kind == 0 else tgt
        if kind == 0:
            if tgt in used_need or used_model.get(m) == "gen":
                conflicts += 1; continue
        else:
            if tgt in used_gen or used_model.get(m) == "trained":
                conflicts += 1; continue
        used_d.update(key)
        if kind == 0:
            used_need.add(tgt); used_model[m] = "trained"
        else:
            used_gen.add(tgt); used_model[m] = "gen"
        fixed.append(j)
    # énergie des rôles impliqués (générateur ou entraîné)
    e = sum(inst.energy[m] for m in used_model)
    while e > inst.cap and fixed:
        j = fixed.pop()
        c, pid, kind, tgt = acol[j]
        m = tgt[0] if kind == 0 else tgt
        if m in used_model and not any((acol[jj][3][0] if acol[jj][2] == 0 else acol[jj][3]) == m for jj in fixed):
            e -= inst.energy[m]; del used_model[m]
        conflicts += 1
    return fixed, len(ca), len(cb), conflicts, e


def choose_rins(a, mdl, inst, x_lp, x0, thr, frac, eps0, rng):
    """RINS classique : fixer les variables où LP et solution courante s'accordent.
    - colonnes de paquets : x0 = 1 et x_lp >= thr -> fixées à 1 ; x0 = 0 et x_lp <= eps0 -> fixées à 0 (sauf une part
      aléatoire 1 - frac laissée libre) ; les autres (support LP hors best/, best/ hors support) restent libres ;
    - en option (--fix-roles) : rôles f/h/y/z fixés à x0 quand |x_lp - x0| <= 1 - thr (sauf part 1 - frac_roles).
    - en option (--lp-one) : colonnes hors best/ de valeur LP >= lp_one fixées à 1 (cohérence dataset/besoin)."""
    nrole = mdl["nrole"]; acol = mdl["acol"]; plist = mdl["plist"]
    xa = x_lp[nrole:]; xb = x0[nrole:]
    one = np.nonzero((xb > 0.5) & (xa >= thr))[0]
    zero = np.nonzero((xb < 0.5) & (xa <= eps0))[0]
    if frac < 1.0:
        zero = zero[rng.random_sample(len(zero)) < frac]
        one = one[rng.random_sample(len(one)) < frac]
    roles = np.array([], np.int64)
    rval = x0[:nrole]
    if a.roles_lp:  # plongeon : rôles fixés à la valeur LP arrondie (quand quasi entière), même si best/ diffère
        xr = x_lp[:nrole]; rval = np.round(xr)
        roles = np.nonzero(np.abs(xr - rval) <= 1.0 - thr)[0]
    elif a.fix_roles:
        xr = x_lp[:nrole]; xr0 = x0[:nrole]
        roles = np.nonzero(np.abs(xr - xr0) <= 1.0 - thr)[0]
        if a.frac_roles < 1.0:
            roles = roles[rng.random_sample(len(roles)) < a.frac_roles]
    extra1 = []
    if a.lp_one < 1.0:
        used_d = set(); used_t = set()
        for j in one.tolist():
            c, pid, kind, tgt = acol[j]
            used_d.update(plist[pid][3]); used_t.add((kind, tgt))
        for j in np.nonzero((xb < 0.5) & (xa >= a.lp_one))[0].tolist():
            c, pid, kind, tgt = acol[j]
            key = plist[pid][3]
            if (kind, tgt) in used_t or any(d in used_d for d in key):
                continue
            used_d.update(key); used_t.add((kind, tgt)); extra1.append(j)
    return one, zero, roles, np.array(extra1, np.int64), rval


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("--start", default=None)
    ap.add_argument("--extra", nargs="*", default=[])
    ap.add_argument("--theta", type=float, default=5.0)
    ap.add_argument("--theta-gen", type=float, default=None)
    ap.add_argument("--k1", type=int, default=10); ap.add_argument("--k2", type=int, default=10); ap.add_argument("--k3", type=int, default=10)
    ap.add_argument("--eps1", type=int, default=300); ap.add_argument("--eps2", type=int, default=5); ap.add_argument("--eps3", type=int, default=0)
    ap.add_argument("--hcols", type=float, default=0.25)
    ap.add_argument("--kcur", type=int, default=10)
    ap.add_argument("--cross", type=int, default=0)
    ap.add_argument("--fix-gen", action="store_true")
    ap.add_argument("--max-cols", type=int, default=250000)
    # LP
    ap.add_argument("--lp-solver", default="ipm")
    ap.add_argument("--lp-threads", type=int, default=2)
    ap.add_argument("--lp-time", type=float, default=900)
    ap.add_argument("--crossover", type=int, default=0)
    ap.add_argument("--lp-recompute", action="store_true")
    # RINS
    ap.add_argument("--thresholds", default="0.95,0.9,0.8", help="seuils successifs (cycle)")
    ap.add_argument("--frac", default="1.0", help="fractions aléatoires des candidats (cycle), ex. 1.0,0.85,0.7")
    ap.add_argument("--support-eps", type=float, default=1e-6)
    ap.add_argument("--rc0", type=float, default=0.0, help="> 0 : fixer à 0 les colonnes hors support de coût réduit >= rc0")
    ap.add_argument("--mode", default="rins", help="rins (accord LP/courant) ou lp (seuil LP + support∩courant)")
    ap.add_argument("--eps0", default="1e-6", help="colonnes hors courant de valeur LP <= eps0 fixées à 0 (cycle)")
    ap.add_argument("--fix-roles", type=int, default=1, help="1 : rôles fixés quand LP et courant s'accordent")
    ap.add_argument("--frac-roles", type=float, default=1.0)
    ap.add_argument("--roles-lp", type=int, default=0, help="1 : plongeon, rôles fixés à la LP arrondie (quasi entiers) au lieu de l'accord")
    ap.add_argument("--lp-one", type=float, default=1.0, help="< 1 : colonnes hors courant de valeur LP >= lp_one fixées à 1")
    ap.add_argument("--cutoff", type=int, default=1, help="1 : ligne objectif >= courant + 1 dans le MIP réduit")
    ap.add_argument("--slice", type=float, default=300, help="temps HiGHS par tour (s)")
    ap.add_argument("--total", type=float, default=3000, help="temps total du processus (s)")
    ap.add_argument("--max-rounds", type=int, default=1000)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0, help="graine du modèle (génération des colonnes)")
    ap.add_argument("--rins-seed", type=int, default=-1, help="graine des tirages RINS (-1 : horloge)")
    ap.add_argument("--tag", default="x")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    k = a.instance
    inst = Instance(k)
    rng = np.random.RandomState(a.seed)
    start = a.start or os.path.join(ROOT, "best", f"instance_{k}.json")
    sol = json.load(open(start))
    start_mtime = os.path.getmtime(start)
    from save_if_better import evaluate, save_if_better
    cur_score, ok, msg = evaluate(k, json.dumps(sol), inst.txt)
    log(f"départ {start} : score {cur_score} valide={ok} ; graine {a.seed} tag {a.tag}")
    mdl = build_model(a, inst, sol, rng)
    x0, nh, nmiss = hint_vector(mdl, inst, sol)
    Ax = mdl["A"] @ x0
    bad = np.nonzero((Ax > mdl["rhi"] + 1e-9) | (Ax < mdl["rlo"] - 1e-9))[0]
    log(f"  hint : {nh} colonnes, {nmiss} manquantes, valeur {-float(np.dot(mdl['obj'], x0)):.0f}, lignes violées {len(bad)}")
    if a.fix_gen:
        for g in mdl["G"]:
            j = mdl["yi"][g]; mdl["lo"][j] = mdl["hi"][j] = x0[j]
        for c, pid, kind, tgt in mdl["acol"]:
            if kind == 1:
                mdl["lo"][c] = mdl["hi"][c] = x0[c]
    x_lp, rc_lp, lp_bound = solve_lp(a, mdl, x0)
    rseed = (a.seed * 7919 + int(time.time())) % (2 ** 31) if a.rins_seed < 0 else a.rins_seed
    rng = np.random.RandomState(rseed)
    log(f"  graine RINS {rseed}")
    thrs = [float(s) for s in a.thresholds.split(",")]
    fracs = [float(s) for s in a.frac.split(",")]
    eps0s = [float(s) for s in a.eps0.split(",")]
    nrole = mdl["nrole"]
    rnd = 0
    results = []
    while rnd < a.max_rounds and time.time() - t0 + 30 < a.total:
        thr = thrs[rnd % len(thrs)]; frac = fracs[(rnd // len(thrs)) % len(fracs)]
        rnd += 1
        # best/ a changé ailleurs ? on s'arrête, la boucle shell repart du nouveau best/
        try:
            if os.path.getmtime(start) != start_mtime:
                so2 = json.load(open(start))
                sc2, ok2, _ = evaluate(k, json.dumps(so2), inst.txt)
                if ok2 and sc2 > cur_score:
                    log(f"  best/ a changé ({sc2} > {cur_score}) : fin du processus pour repartir du nouveau best/")
                    break
                start_mtime = os.path.getmtime(start)
        except Exception as e:
            log(f"  lecture de {start} : {e!r}")
        lo = mdl["lo"].copy(); hi = mdl["hi"].copy(); rhi = mdl["rhi"].copy()
        eps0 = eps0s[(rnd // (len(thrs) * len(fracs))) % len(eps0s)]
        nz0 = 0; nrf = 0; desc = ""
        if a.mode == "rins":
            one, zero, roles, extra1, rval = choose_rins(a, mdl, inst, x_lp, x0, thr, frac, eps0, rng)
            if a.roles_lp:  # colonnes de best/ incompatibles avec les rôles LP : non fixées
                keep = np.array([rval[mdl["zi"][tgt]] > 0.5 if kind == 0 else rval[mdl["yi"][tgt]] > 0.5
                                 for (c, pid, kind, tgt) in (mdl["acol"][j] for j in one)], bool) if len(one) else np.zeros(0, bool)
                one = one[keep]
            lo[nrole + one] = 1.0; hi[nrole + one] = 1.0
            hi[nrole + zero] = 0.0; nz0 = len(zero)
            lo[roles] = rval[roles]; hi[roles] = rval[roles]; nrf = len(roles)
            lo[nrole + extra1] = 1.0; hi[nrole + extra1] = 1.0
            fixed = one.tolist() + extra1.tolist()
            desc = f"un {len(one)} (+{len(extra1)} LP), zéro {nz0}, rôles {nrf}, libres {mdl['ncol'] - len(fixed) - nz0 - nrf}"
        else:
            fixed, na, nb, conf, e = choose_fixed(a, mdl, inst, x_lp, x0, thr, frac, rng)
            jf = np.array([mdl["acol"][j][0] for j in fixed], np.int64)
            lo[jf] = 1.0; hi[jf] = 1.0
            desc = f"un {len(fixed)} (a {na}, b {nb}, conflits {conf}, énergie {e / inst.cap:.3f})"
        if a.rc0 > 0:
            z0 = np.nonzero((x_lp[nrole:] <= a.support_eps) & (rc_lp[nrole:] >= a.rc0))[0]
            hi[nrole + z0] = 0.0; nz0 = len(z0)
        if a.cutoff:
            rhi[mdl["RC"]] = -(cur_score + 1) + 1e-6
        slice_t = min(a.slice, a.total - (time.time() - t0) - 20)
        if slice_t < 30:
            break
        h = new_highs(a, a.threads, (rseed + rnd) % 2147483647)
        h.setOptionValue("time_limit", float(slice_t))
        h.setOptionValue("mip_rel_gap", 0.0)
        pass_model(h, mdl, lo, hi, rhi, True)
        import highspy
        s0 = highspy.HighsSolution(); s0.col_value = list(x0); h.setSolution(s0)
        t1 = time.time()
        h.run()
        dt = time.time() - t1
        info = h.getInfo(); st = h.modelStatusToString(h.getModelStatus())
        bound = -float(info.mip_dual_bound) if info.mip_dual_bound and abs(info.mip_dual_bound) < 1e15 else None
        xs = np.array(h.getSolution().col_value)
        val = None; sc = None; okv = False
        if len(xs) == mdl["ncol"] and info.primal_solution_status != 0:
            x = np.round(xs)
            val = -float(np.dot(mdl["obj"], x))
            out = decode(mdl, inst, x)
            txt = json.dumps(out, separators=(",", ":"))
            sc, okv, msg = evaluate(k, txt, inst.txt)
            if okv and sc > cur_score:
                outf = os.path.join(ROOT, "runs", f"m9_rins_{a.tag}_r{rnd}.json")
                with open(outf, "w") as f:
                    f.write(txt)
                log(f"  *** AMÉLIORATION {cur_score} -> {sc} (écrit {outf})")
                if a.save:
                    rc_, sc_ = save_if_better(k, txt, method=f"m9 rins seuil={thr} frac={frac} cutoff={a.cutoff} "
                                              f"theta={a.theta} k={a.k1} fixgen={int(a.fix_gen)} seed={a.seed} tag={a.tag}",
                                              dataset_txt=inst.txt)
                    log(f"  save_if_better -> code {rc_} (score {sc_})")
                    try:
                        start_mtime = os.path.getmtime(start)
                    except Exception:
                        pass
                cur_score = sc; sol = out
                x0, nh, nmiss = hint_vector(mdl, inst, sol)
        results.append((rnd, thr, frac, len(fixed), st, val, bound, dt))
        log(f"TOUR {rnd} seuil={thr} frac={frac} eps0={eps0} : {desc} ; HiGHS {st} en {dt:.0f}s ; "
            f"valeur {val} (score {sc} valide={okv}) borne {bound} ; nœuds {info.mip_node_count} ; "
            f"courant {cur_score} ; LP {lp_bound:.1f}")
    log(f"fin : {rnd} tours, score courant {cur_score}, total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
