#!/usr/bin/env python3
"""LNS exact sur les rôles (instance sans générateurs, ex. 4) : sous-MIP HiGHS sur ~q modèles libérés.

État = rôle par modèle (0, f, h). À chaque itération : on libère q modèles (tirés parmi le cœur à faible coût réduit
LP, en mélangeant pris / non pris), on résout exactement le sous-problème (valeur max, puis départage : marge
pondérée par les duaux LP maximale) avec les ressources résiduelles (énergie, données libres et totales par type).
Accepté si valeur > ou (= et marge pondérée >=). Énergie en entiers exacts vérifiée à chaque acceptation.

Usage : python src/fin_lns4.py <k> [--time 1800] [--q 40] [--seed 1] [--gapfix 30] [--target T]
Sortie : runs/fin_lns_roles_<k>_s<seed>.json (meilleur), rôles au format lp_bound.py
"""
import argparse
import json
import os
import random
import sys
import time

import numpy as np
from scipy.optimize import linprog

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402
from fin_mip4 import build, hint_from_best  # noqa: E402
import highspy  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("--time", type=float, default=1800)
    ap.add_argument("--q", type=int, default=40)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--gapfix", type=float, default=30.0, help="cœur = modèles avec une option de |coût réduit| <= gapfix")
    ap.add_argument("--target", type=float, default=0)
    ap.add_argument("--start", default=None, help="fichier de rôles de départ (défaut : best/)")
    ap.add_argument("--sub-time", type=float, default=5.0)
    ap.add_argument("--plateau", action="store_true", help="départage aléatoire : marche sur le plateau de valeur égale")
    a = ap.parse_args()
    k = a.instance
    rng = random.Random(a.seed)
    inst = Instance(k)
    nm = len(inst.value)
    obj, ub, A, rhs = build(inst)
    res = linprog(obj, A_ub=A.tocsr(), b_ub=rhs, bounds=list(zip([0.0] * len(obj), ub)), method="highs")
    rc = np.abs(res.lower.marginals + res.upper.marginals)
    du = -res.ineqlin.marginals[:9]
    bound = -res.fun
    # ressources exactes : 0 énergie, 1-4 libres, 5-8 totales
    F = [0] * 4
    T = [0] * 4
    for t, s, c in inst.ds:
        T[t] += s
        if not c:
            F[t] += s
    cap = np.array([inst.cap] + F + T, dtype=np.int64)
    use_f = np.zeros((nm, 9), dtype=np.int64)
    for m in range(nm):
        use_f[m, 0] = inst.energy[m]
        for t, lb, _ in inst.reqs[m]:
            use_f[m, 1 + t] += lb; use_f[m, 5 + t] += lb
    use_h = use_f.copy(); use_h[:, 1:5] = 0
    val_f = np.array(inst.value); val_h = val_f // 2
    feas = ub[0::2] > 0.5
    w = du * np.array([1e-6] + [1] * 8)  # prix dual par unité exacte

    if a.start:
        r = json.load(open(a.start))
        role = np.array([1 if r["f"][m] > .5 else 2 if r["h"][m] > .5 else 0 for m in range(nm)])
    else:
        x0 = hint_from_best(inst, k)
        role = np.array([1 if x0[2 * m] > .5 else 2 if x0[2 * m + 1] > .5 else 0 for m in range(nm)])

    def totals(role):
        u = use_f[role == 1].sum(0) + use_h[role == 2].sum(0)
        v = int(val_f[role == 1].sum() + val_h[role == 2].sum())
        return u, v
    u, v = totals(role)
    assert np.all(u <= cap), "départ infaisable"
    core = [m for m in range(nm) if feas[m] and min(rc[2 * m], rc[2 * m + 1]) <= a.gapfix]
    print(f"inst {k}: départ {v}, borne LP {bound:.2f}, cœur {len(core)} modèles (gapfix {a.gapfix})", flush=True)
    best_v = v
    out = os.path.join(ROOT, "runs", f"fin_lns_roles_{k}_s{a.seed}.json")

    def dump(role):
        with open(out, "w") as f:
            json.dump({"value": float(totals(role)[1]), "f": [float(x == 1) for x in role],
                       "h": [float(x == 2) for x in role], "y": [0.0] * nm, "z": [[] for _ in range(nm)]}, f)

    t0 = time.time()
    it = acc = imp = 0
    while time.time() - t0 < a.time and (not a.target or best_v < a.target):
        it += 1
        q = rng.randint(max(6, a.q // 3), a.q)
        S = rng.sample(core, q)
        resid = cap - (u - sum(use_f[m] if role[m] == 1 else use_h[m] if role[m] == 2 else 0 for m in S))
        cur_v_S = sum(int(val_f[m]) if role[m] == 1 else int(val_h[m]) if role[m] == 2 else 0 for m in S)
        # sous-MIP : variables f_m, h_m pour m dans S ; objectif = valeur + eps * marge pondérée
        n = 2 * q
        cost = np.zeros(n); lo = np.zeros(n); hi = np.ones(n)
        rows = [[] for _ in range(9 + q)]
        Ar, Ac, Av = [], [], []
        for i, m in enumerate(S):
            for o, (val, use) in enumerate(((val_f[m], use_f[m]), (val_h[m], use_h[m]))):
                j = 2 * i + o
                if a.plateau:
                    cost[j] = -(val + 1e-3 * rng.uniform(-1, 1))  # départage aléatoire
                else:
                    cost[j] = -(val - 1e-3 * float(w @ use))  # départage : moins de ressources consommées
                for rr in range(9):
                    if use[rr]:
                        Ar.append(rr); Ac.append(j); Av.append(float(use[rr]) * (1e-6 if rr == 0 else 1.0))
                Ar.append(9 + i); Ac.append(j); Av.append(1.0)
            if not feas[m]:
                hi[2 * i] = hi[2 * i + 1] = 0
        rup = np.array([resid[0] * 1e-6 - 1e-6] + [float(x) for x in resid[1:]] + [1.0] * q)
        from scipy.sparse import coo_matrix
        M = coo_matrix((Av, (Ar, Ac)), shape=(9 + q, n)).tocsc()
        h = highspy.Highs()
        h.setOptionValue("output_flag", False)
        h.setOptionValue("threads", 1)
        h.setOptionValue("time_limit", a.sub_time)
        h.setOptionValue("mip_rel_gap", 0.0)
        lp = highspy.HighsLp()
        lp.num_col_ = n; lp.num_row_ = 9 + q
        lp.col_cost_ = cost; lp.col_lower_ = lo; lp.col_upper_ = hi
        lp.row_lower_ = np.full(9 + q, -np.inf); lp.row_upper_ = rup
        lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
        lp.a_matrix_.start_ = M.indptr.astype(np.int32); lp.a_matrix_.index_ = M.indices.astype(np.int32)
        lp.a_matrix_.value_ = M.data
        lp.integrality_ = [highspy.HighsVarType.kInteger] * n
        h.passModel(lp)
        xs0 = np.zeros(n)
        for i, m in enumerate(S):
            if role[m]:
                xs0[2 * i + role[m] - 1] = 1
        s0 = highspy.HighsSolution(); s0.col_value = list(xs0); h.setSolution(s0)
        h.run()
        if not h.getInfo().primal_solution_status:
            if it <= 3:
                print("  sous-MIP sans solution :", h.modelStatusToString(h.getModelStatus()), flush=True)
            continue
        xs = np.round(np.array(h.getSolution().col_value))
        new = role.copy()
        for i, m in enumerate(S):
            new[m] = 1 if xs[2 * i] > .5 else 2 if xs[2 * i + 1] > .5 else 0
        nu, nv = totals(new)
        if np.any(nu > cap):
            if it <= 3:
                print("  dépassement", nu - cap, flush=True)
            continue  # tolérance numérique : on rejette
        if nv > v or (nv == v and (a.plateau or float(w @ nu) <= float(w @ u))):
            if nv > v or np.any(new != role):
                acc += 1
            if nv > v:
                imp += 1
            role, u, v = new, nu, nv
            if v > best_v:
                best_v = v
                dump(role)
                print(f"  {time.time()-t0:.0f}s it {it}: {v}  (marge pondérée {float(w @ (cap - u)):.2f})", flush=True)
        if it % 200 == 0:
            print(f"  {time.time()-t0:.0f}s it {it} acc {acc} valeur {v} marge pondérée {float(w @ (cap - u)):.2f}",
                  flush=True)
    dump(role) if best_v == v else None
    print(f"fin : {best_v} ({it} itérations)", flush=True)


if __name__ == "__main__":
    main()
