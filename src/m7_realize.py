#!/usr/bin/env python3
"""m7 — Rôles (MIP des rôles avec offre libre réduite) puis RÉALISATION EXACTE par type avec un MIP d'affectation
x[d, créneau] (HiGHS) : les créneaux plein tarif d'un type reçoivent les datasets libres du type, somme ∈ [lb, ub].
Un modèle dont un créneau n'est pas satisfait est rétrogradé en demi-tarif (copyrightés, abondants).
Usage : python src/m7_realize.py 2 --shrink 900 --time-roles 120 --time-pack 240 --threads 6 --out runs/m7_real_2.json --save
        python src/m7_realize.py 2 --roles-from-best  (test : ré-empaqueter l'ensemble f de best)
"""
import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance, Pools  # noqa: E402
from save_if_better import evaluate  # noqa: E402
from m7_roles import Roles  # noqa: E402
from m7_cg import packets_of_solution, log  # noqa: E402


def pack_type(inst, t, fmodels, free, time_limit, threads, hint_pk=None, min_size=True, exact=300, solver="highs"):
    """MIP d'affectation pour le type t. fmodels : modèles f ayant un besoin t. free : [(size, id)] libres de type t.
    Retourne (assign {m: [ids]}, inactive set(m), info)."""
    import highspy
    slots = [(m, lb, u) for m in fmodels for tt, lb, u in inst.reqs[m] if tt == t]
    nk = len(slots); nd = len(free)
    if nk == 0:
        return {}, set(), "aucun créneau"
    # colonnes : a_k (activation, coût -w_k), puis x[d,k] (coût eps*size)
    cost, lo, up, cidx, cval = [], [], [], [], []
    # lignes : 0..nd-1 datasets (<=1) ; nd+2k : Σ s x - lb a >= 0 ; nd+2k+1 : Σ s x - ub a <= 0
    row_lo = [-np.inf] * nd + [0.0, -np.inf] * nk
    row_hi = [1.0] * nd + [np.inf, 0.0] * nk
    for k, (m, lb, u) in enumerate(slots):
        w = (inst.value[m] - inst.value[m] // 2) / len(inst.reqs[m])
        cost.append(-w); lo.append(0.0); up.append(1.0); cidx.append([nd + 2 * k, nd + 2 * k + 1]); cval.append([-float(lb), -float(u)])
    xi = {}
    eps = 1e-6 if min_size else 0.0
    for j, (s, d) in enumerate(free):
        for k, (m, lb, u) in enumerate(slots):
            if s <= u:
                xi[(j, k)] = len(cost)
                cost.append(eps * s); lo.append(0.0); up.append(1.0)
                cidx.append([j, nd + 2 * k, nd + 2 * k + 1]); cval.append([1.0, float(s), float(s)])
    n = len(cost)
    h = highspy.Highs()
    h.setOptionValue("output_flag", False); h.setOptionValue("threads", threads)
    h.setOptionValue("time_limit", float(time_limit)); h.setOptionValue("mip_rel_gap", 0.0)
    lp = highspy.HighsLp()
    lp.num_col_ = n; lp.num_row_ = len(row_lo)
    lp.col_cost_ = np.array(cost); lp.col_lower_ = np.array(lo); lp.col_upper_ = np.array(up)
    lp.row_lower_ = np.array(row_lo); lp.row_upper_ = np.array(row_hi)
    starts = np.zeros(n + 1, dtype=np.int32); starts[1:] = np.cumsum([len(c) for c in cidx])
    lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    lp.a_matrix_.start_ = starts
    lp.a_matrix_.index_ = np.concatenate([np.array(c, dtype=np.int32) for c in cidx])
    lp.a_matrix_.value_ = np.concatenate([np.array(c, dtype=np.float64) for c in cval])
    lp.integrality_ = [highspy.HighsVarType.kInteger] * n
    h.passModel(lp)
    # hint : paquets connus (best) pour les créneaux communs, puis glouton subset-sum exact (gros d'abord) pour les autres
    hint_pk = dict(hint_pk or {})
    pools = Pools(inst); pools.exact = exact
    for tt in range(4):
        pools.p[tt][1] = []  # datasets copyrightés exclus
    kof0 = {m: k for k, (m, lb, u) in enumerate(slots)}
    for m in list(hint_pk):
        if m not in kof0:
            del hint_pk[m]
        else:
            for d in hint_pk[m]:
                pools.remove(pools.p[t][0], (inst.ds[d][1], d))
    ngl = 0
    for m, lb, u in sorted(slots, key=lambda r: r[2] - r[1]):  # fenêtres étroites d'abord
        if m in hint_pk:
            continue
        tk = pools.fill(t, lb, u, [0])
        if tk is not None:
            hint_pk[m] = [d for s_, d, c in tk]; ngl += 1
    if solver == "cpsat":
        import tempfile
        inp = {"slots": [[m, lb, u, (inst.value[m] - inst.value[m] // 2) / len(inst.reqs[m])] for m, lb, u in slots],
               "free": [[s_, d] for s_, d in free], "hint": {str(m): ids for m, ids in hint_pk.items()},
               "time": time_limit, "workers": threads}
        fi = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, dir=os.path.join(ROOT, "runs")); json.dump(inp, fi); fi.close()
        fo = fi.name + ".out"
        t0 = time.time()
        subprocess.run([sys.executable, os.path.join(ROOT, "src", "m7_pack_cp.py"), fi.name, fo])
        res = json.load(open(fo)); os.unlink(fi.name); os.unlink(fo)
        assign = {int(m): ids for m, ids in res["assign"].items()}
        for m, ids in assign.items():
            lb, u = [(lb, u) for mm_, lb, u in slots if mm_ == m][0]
            ssum = sum(inst.ds[d][1] for d in ids); assert lb <= ssum <= u
        inactive = {m for m, lb, u in slots if m not in assign}
        used = sum(inst.ds[d][1] for ids in assign.values() for d in ids); tot = sum(s_ for s_, d in free)
        return assign, inactive, (f"type {t} CP-SAT: {nk} créneaux, hint {len(hint_pk)}, {res['status']}, actifs {len(assign)}/{nk}, "
                                  f"obj {res.get('obj')} borne {res.get('bound')}, libres utilisés {used}/{tot}, {time.time()-t0:.0f}s")
    if hint_pk:
        x0 = np.zeros(n)
        pos = {d: j for j, (s, d) in enumerate(free)}
        kof = {m: k for k, (m, lb, u) in enumerate(slots)}
        nh = 0
        for m, ids in hint_pk.items():
            if m in kof and all(d in pos and (pos[d], kof[m]) in xi for d in ids):
                x0[kof[m]] = 1
                for d in ids:
                    x0[xi[(pos[d], kof[m])]] = 1
                nh += 1
        s0 = highspy.HighsSolution(); s0.col_value = list(x0); h.setSolution(s0)
        log(f"    hint type {t}: {nh}/{nk} créneaux (dont {ngl} gloutons)")
    t0 = time.time()
    h.run()
    info = h.getInfo()
    st = h.modelStatusToString(h.getModelStatus())
    if not info.primal_solution_status:
        return None, set(slots), f"type {t}: pas de solution ({st})"
    x = np.array(h.getSolution().col_value)
    assign, inactive = {}, set()
    for k, (m, lb, u) in enumerate(slots):
        if x[k] > 0.5:
            ids = [free[j][1] for j in range(nd) if (j, k) in xi and x[xi[(j, k)]] > 0.5]
            ssum = sum(inst.ds[d][1] for d in ids)
            assert lb <= ssum <= u, (m, lb, ssum, u)
            assign[m] = ids
        else:
            inactive.add(m)
    used = sum(inst.ds[d][1] for ids in assign.values() for d in ids)
    tot = sum(s for s, d in free)
    return assign, inactive, (f"type {t}: {nk} créneaux, {nd} datasets, {n} var., {st}, actifs {len(assign)}/{nk}, "
                              f"borne {-info.mip_dual_bound:.1f} obj {-info.objective_function_value:.1f}, libres utilisés {used}/{tot}, {time.time()-t0:.0f}s")


def assemble(inst, fassign, hset, yset, z, exact=300):
    """fassign : {m: [ids]} (tous créneaux de m) ; hset/yset : ensembles ; z : {m: [types]} -> solution JSON."""
    pools = Pools(inst); pools.exact = exact
    dm = []
    for m, ids in fassign.items():
        for d in ids:
            t, s, c = inst.ds[d]
            pools.remove(pools.p[t][c], (s, d)); dm.append([d, m])
    ysrc = {t: [] for t in range(4)}
    dropped = set()
    for m in sorted(yset, key=lambda m: inst.reqs[m][0][2] - inst.reqs[m][0][1]):
        t, lb, u = inst.reqs[m][0]
        tk = pools.fill(t, lb, u, [1, 0])
        if tk is None:
            dropped.add(m); continue
        for s, d, c in tk:
            dm.append([d, m])
        ysrc[t].append(m)
    mm = []
    hs = sorted(hset, key=lambda m: min((u - lb for t, lb, u in inst.reqs[m] if t not in z.get(m, [])), default=10**9))
    for m in hs:
        zz = z.get(m, [])
        need = [(t, lb, u) for t, lb, u in inst.reqs[m] if t not in zz]
        ok = all(len(ysrc[t]) > 0 for t in zz)
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
        for t in zz:
            mm.append([ysrc[t].pop(), m])
    for t in range(4):
        for m in ysrc[t]:
            dropped.add(m)
    dm = [[d, m] for d, m in dm if m not in dropped]
    return {"dataMappings": dm, "modelMappings": mm}, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("--shrink", type=float, nargs="*", default=[900.0])
    ap.add_argument("--roles-from-best", action="store_true")
    ap.add_argument("--roles-file", default=None, help="fichier de rôles (f,h,y,z) existant")
    ap.add_argument("--time-roles", type=float, default=120)
    ap.add_argument("--time-pack", type=float, default=240)
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--out", default=None)
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--pack", default="highs", choices=["highs", "cpsat"])
    ap.add_argument("--iters", type=int, default=1, help="itérations : les modèles non réalisables sont interdits en f")
    ap.add_argument("--until", type=float, default=1e9, help="durée totale max (s)")
    a = ap.parse_args()
    k = a.instance
    inst = Instance(k)
    nm = len(inst.value)
    sol0 = json.load(open(os.path.join(ROOT, "best", f"instance_{k}.json")))
    roles0, pk0 = packets_of_solution(inst, sol0)
    hint_pk = {}
    for (m, t), ids in pk0.items():
        hint_pk.setdefault(t, {})[m] = ids
    R = Roles(inst)
    x0 = R.roles_of_solution(sol0)
    t0 = time.time()
    forbid = set()      # modèles interdits en f (créneau non réalisable aux itérations précédentes)
    prev_pk = {}        # paquets réalisés à l'itération précédente (hint)
    best_v = 0
    for it in range(a.iters):
        if time.time() - t0 > a.until:
            log("limite de temps globale atteinte"); break
        if a.roles_from_best:
            x = x0
        elif a.roles_file:
            ro = json.load(open(a.roles_file))
            x = np.zeros(R.ncol)
            for m in range(nm):
                if ro["f"][m] > 0.5: x[R.fi[m]] = 1
                if ro["h"][m] > 0.5:
                    x[R.hi[m]] = 1
                    for t in ro["z"][m]: x[R.zi[(m, t)]] = 1
                if ro["y"][m] > 0.5 and m in R.yi: x[R.yi[m]] = 1
        else:
            sh = a.shrink if len(a.shrink) == 4 else [a.shrink[0]] * 4
            ub = R.ub.copy()
            for m in forbid:
                ub[R.fi[m]] = 0.0
            hint = x0 if all(x0[R.fi[m]] < 0.5 for m in forbid) else None
            res = R.solve(integer=True, time_limit=a.time_roles, threads=a.threads, hint=hint, shrink=sh, ub=ub)
            x = np.round(res["x"])
            log(f"it {it} rôles MIP (shrink {sh}, {len(forbid)} interdits) : valeur {res['value']:.0f} borne {res['bound']:.1f} {res['status']} ({time.time()-t0:.0f}s)")
        f = [m for m in range(nm) if x[R.fi[m]] > 0.5]
        h = {m for m in range(nm) if x[R.hi[m]] > 0.5}
        y = {m for m in R.yi if x[R.yi[m]] > 0.5}
        z = {m: [t for t, _, _ in inst.reqs[m] if x[R.zi[(m, t)]] > 0.5] for m in h}
        vrole = sum(inst.value[m] for m in f) + sum(inst.value[m] // 2 for m in h)
        log(f"it {it} rôles : f {len(f)} h {len(h)} y {len(y)} ; valeur rôles {vrole}")
        if a.out:
            json.dump({"f": [1.0 if m in set(f) else 0.0 for m in range(nm)], "h": [1.0 if m in h else 0.0 for m in range(nm)],
                       "y": [1.0 if m in y else 0.0 for m in range(nm)], "z": [z.get(m, []) for m in range(nm)], "value": vrole},
                      open(a.out + f".roles{it}.json", "w"))
        free = [[] for _ in range(4)]
        for i, (t, s, c) in enumerate(inst.ds):
            if not c:
                free[t].append((s, i))
        fassign = {m: [] for m in f}
        demoted = set()
        for t in range(4):
            fm = [m for m in f if any(tt == t for tt, _, _ in inst.reqs[m])]
            hp = dict(hint_pk.get(t, {}))
            hp.update(prev_pk.get(t, {}))  # les paquets de l'itération précédente priment
            assign, inactive, info = pack_type(inst, t, fm, free[t], a.time_pack, a.threads, hp, solver=a.pack)
            log("  " + str(info))
            if assign is None:
                demoted |= set(fm); continue
            prev_pk[t] = dict(assign)
            for m, ids in assign.items():
                fassign[m] += ids
            demoted |= inactive
        for m in demoted:
            fassign.pop(m, None)
        h2 = h | demoted
        log(f"it {it} rétrogradés f->h : {len(demoted)} (perte {sum(inst.value[m] - inst.value[m]//2 for m in demoted)}) : {sorted(demoted)}")
        sol, dropped = assemble(inst, fassign, h2, y, z)
        txt = json.dumps(sol)
        v, ok, msg = evaluate(k, txt)
        log(f"it {it} solution : {v} valide={ok} {msg} ; abandonnés {len(dropped)} ; {time.time()-t0:.0f}s")
        if a.out and ok and v > best_v:
            best_v = v
            open(a.out, "w").write(txt)
            if a.save:
                subprocess.run([sys.executable, os.path.join(ROOT, "src", "save_if_better.py"), str(k), a.out,
                                "--method", f"m7 rôles shrink={a.shrink} + réalisation {a.pack} par type (it {it})"])
        if not demoted or a.roles_from_best or a.roles_file:
            break
        forbid |= demoted


if __name__ == "__main__":
    main()
