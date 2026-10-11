#!/usr/bin/env python3
"""m10 : CP-SAT GLOBAL (rôles + affectation datasets -> créneaux) sur toute l'instance, réduit par fixation.

Modèle : pour chaque modèle m LIBRE, f_m (plein), h_m (demi), y_m (générateur, mono réalisable), z[m,t] (besoin t
couvert par un générateur, z <= h ; z = h si lb > ub) ; f + h + y <= 1. Créneau (m,t) actif a = f + h - z (ou y pour
un générateur) : lb·a <= somme des tailles <= ub·a. Dataset <= 1 créneau ; copyright interdit si f (x + f <= 1).
Par type : nb de cibles couvertes <= nb de générateurs. Énergie <= cap. Objectif = score exact du concours.
Les modèles dont le rôle est identique dans toutes les solutions du pool (+ hint) sont FIXÉS (constantes).
Support des x[d, créneau] :
  A. toutes les paires (dataset, créneau) des solutions du pool + hint ;
  B. tous les datasets compatibles pour les créneaux des modèles libres (--full-free) ;
  C. datasets de taille <= --small pour tous les créneaux actifs de leur type.
Hint complet = solution de départ. Chaque solution améliorante est décodée, validée (scoreur officiel) et passée à
src/save_if_better.py.

Usage : python src/m10_cp.py 6 --pool 'runs/m10_pool/*.json' [--hint best/instance_6.json] [--lpk 150] [--small 600]
        [--full-free] [--targets 100] [--time 600] [--rounds 1] [--workers 16] [--seed 0] [--tag x] [--stats] [--fix-hint]
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402
from save_if_better import evaluate  # noqa: E402


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def roles_of(inst, sol):
    """role[m] = ('F',) | ('H', frozenset(types couverts)) | ('Y',) | None ; packs {(m,t): set(d)}"""
    src = {s for s, _ in sol["modelMappings"]}
    cov = defaultdict(set)
    for s, t in sol["modelMappings"]:
        cov[t].add(inst.reqs[s][0][0])
    byd = defaultdict(list)
    for d, m in sol["dataMappings"]:
        byd[m].append(d)
    trained = (set(byd) | set(cov)) - src
    role = [None] * len(inst.value)
    for m in trained:
        half = any(inst.ds[d][2] for d in byd[m]) or bool(cov[m])
        role[m] = ("H", frozenset(cov[m])) if half else ("F",)
    for g in src:
        role[g] = ("Y",)
    packs = defaultdict(set)
    for d, m in sol["dataMappings"]:
        packs[(m, inst.ds[d][0])].add(d)
    return role, packs


def lp_reduced_costs(inst, lp):
    """coûts réduits (approx.) des rôles f / h / y d'après les duaux de runs/lp_k.json"""
    lam = lp["dual_energy"]
    df, dt, dg = lp["dual_free"], lp["dual_total"], lp["dual_gen"]
    rc = {}
    for m in range(len(inst.value)):
        e = lam * inst.energy[m] / inst.cap
        feas = all(lb <= ub for _, lb, ub in inst.reqs[m])
        rf = inst.value[m] - e - sum(lb * (df[t] + dt[t]) for t, lb, _ in inst.reqs[m]) if feas else -1e9
        rh = inst.value[m] // 2 - e - sum(min(lb * dt[t] if lb <= ub else 1e9, dg[t]) for t, lb, ub in inst.reqs[m])
        ry = (-e - inst.reqs[m][0][1] * dt[inst.reqs[m][0][0]] + dg[inst.reqs[m][0][0]]) if inst.gen_ok[m] else -1e9
        rc[m] = (rf, rh, ry)
    return rc


class Model:
    def __init__(self, inst, hint_sol, pool_sols, a):
        from ortools.sat.python import cp_model
        self.cp = cp_model
        self.inst = inst
        self.a = a
        nm, nd = len(inst.value), len(inst.ds)
        self.hint_role, self.hint_packs = roles_of(inst, hint_sol)
        self.hint_dm = [tuple(p) for p in hint_sol["dataMappings"]]
        pool_roles = [roles_of(inst, s) for s in pool_sols]
        # ---- modèles libres ----
        free = set()
        self.type = a.type
        elig = (lambda m: True) if a.type is None else (lambda m: all(tt == a.type for tt, _, _ in inst.reqs[m]))
        for m in range(nm):
            r0 = self.hint_role[m]
            if elig(m) and any(r[0][m] != r0 for r in pool_roles):
                free.add(m)
        n_pool_free = len(free)
        lp = json.load(open(os.path.join(ROOT, "runs", f"lp_{inst.k}.json")))
        rc = lp_reduced_costs(inst, lp)
        unused = [m for m in range(nm) if self.hint_role[m] is None and elig(m)]
        for key in range(3):
            for m in sorted(unused, key=lambda m: -rc[m][key])[:a.lpk]:
                free.add(m)
        n_lp = len(free) - n_pool_free
        # cibles (demi, couvertes) candidates à la bascule h -> f : meilleur coût réduit f
        targets = [m for m in range(nm) if self.hint_role[m] is not None and self.hint_role[m][0] == "H" and elig(m)]
        for m in sorted(targets, key=lambda m: -rc[m][0])[:a.targets]:
            free.add(m)
        # modèles entraînés / générateurs au pire coût réduit (candidats au retrait)
        used_f = [m for m in range(nm) if self.hint_role[m] is not None and self.hint_role[m][0] == "F" and elig(m)]
        for m in sorted(used_f, key=lambda m: rc[m][0])[:a.worst]:
            free.add(m)
        used_y = [m for m in range(nm) if self.hint_role[m] is not None and self.hint_role[m][0] == "Y" and elig(m)]
        for m in sorted(used_y, key=lambda m: rc[m][2])[:a.worst]:
            free.add(m)
        self.free = free
        log(f"modèles libres {len(free)} (pool {n_pool_free}, LP +{n_lp}, cibles h->f {a.targets}, pires {2 * a.worst}) ; "
            f"fixés {nm - len(free)}")
        m_ = cp_model.CpModel()
        self.m = m_
        # ---- variables de rôle ----
        self.f, self.h, self.y, self.z = {}, {}, {}, {}
        for m in free:
            feas = all(lb <= ub for _, lb, ub in inst.reqs[m])
            if feas:
                self.f[m] = m_.NewBoolVar(f"f{m}")
            self.h[m] = m_.NewBoolVar(f"h{m}")
            if inst.gen_ok[m]:
                self.y[m] = m_.NewBoolVar(f"y{m}")
            m_.AddAtMostOne([v for v in (self.f.get(m), self.h.get(m), self.y.get(m)) if v is not None])
            for t, lb, ub in inst.reqs[m]:
                zv = m_.NewBoolVar(f"z{m}_{t}")
                self.z[(m, t)] = zv
                if lb > ub:
                    m_.Add(zv == self.h[m])
                else:
                    m_.AddImplication(zv, self.h[m])
        # ---- créneaux : (m, t) -> activité (constante 1 ou expression) ----
        self.slots = {}   # sid -> dict(t, lb, ub, act (None=1 | expr), copyr_ok (True|False|'var'), kind)
        for m in range(nm):
            r = self.hint_role[m]
            if m in free:
                for t, lb, ub in inst.reqs[m]:
                    if len(inst.reqs[m]) == 1 and inst.gen_ok[m]:
                        # mono : créneau unique partagé par f / h / y : actif si f + h - z + y
                        act = sum(v for v in (self.f.get(m), self.h.get(m), self.y.get(m)) if v is not None) - self.z[(m, t)]
                    else:
                        act = sum(v for v in (self.f.get(m), self.h.get(m)) if v is not None) - self.z[(m, t)]
                    self.slots[(m, t)] = dict(t=t, lb=lb, ub=ub, act=act, cr="var", kind="free")
            elif r is None:
                continue
            elif r[0] == "F":
                for t, lb, ub in inst.reqs[m]:
                    self.slots[(m, t)] = dict(t=t, lb=lb, ub=ub, act=None, cr=False, kind="F")
            elif r[0] == "H":
                for t, lb, ub in inst.reqs[m]:
                    if t not in r[1]:
                        self.slots[(m, t)] = dict(t=t, lb=lb, ub=ub, act=None, cr=True, kind="H")
            else:
                t, lb, ub = inst.reqs[m][0]
                self.slots[(m, t)] = dict(t=t, lb=lb, ub=ub, act=None, cr=True, kind="Y")
        if a.type is not None:
            self.slots = {sid: s for sid, s in self.slots.items() if s["t"] == a.type}
        # ---- support des x ----
        cand = defaultdict(set)  # sid -> datasets
        for d, m in hint_sol["dataMappings"]:
            cand[(m, inst.ds[d][0])].add(d)
        nA = sum(len(v) for v in cand.values())
        for s in pool_sols:
            for d, m in s["dataMappings"]:
                cand[(m, inst.ds[d][0])].add(d)
        nA2 = sum(len(v) for v in cand.values())
        ds_by_t = defaultdict(list)
        for d, (t, sz, c) in enumerate(inst.ds):
            ds_by_t[t].append(d)
        if a.type is not None:
            cand = defaultdict(set, {sid: dl for sid, dl in cand.items() if sid[1] == a.type})
        if a.full_free:
            for sid, s in self.slots.items():
                if s["kind"] == "free":
                    for d in ds_by_t[s["t"]]:
                        if inst.ds[d][1] <= s["ub"]:
                            cand[sid].add(d)
        nB = sum(len(v) for v in cand.values())
        if a.small > 0:
            for sid, s in self.slots.items():
                for d in ds_by_t[s["t"]]:
                    if inst.ds[d][1] <= a.small and (s["cr"] or not inst.ds[d][2]):
                        cand[sid].add(d)
        nC = sum(len(v) for v in cand.values())
        # filtrage : créneau existant, taille <= ub, copyright
        self.x = {}
        by_d = defaultdict(list)
        by_s = defaultdict(list)
        sids_of_d = defaultdict(list)
        for sid, dl in cand.items():
            if sid not in self.slots:
                continue  # créneau d'un modèle qui n'est pas de ce rôle dans le hint (ex. pool) : ignoré sauf si libre
            s = self.slots[sid]
            for d in dl:
                t, sz, c = inst.ds[d]
                if t != s["t"] or sz > s["ub"] or (c and s["cr"] is False):
                    continue
                v = m_.NewBoolVar(f"x{d}_{sid[0]}_{sid[1]}")
                self.x[(d, sid)] = v
                by_d[d].append(v)
                by_s[sid].append((sz, v))
                sids_of_d[d].append(sid)
                if c and s["cr"] == "var" and sid[0] in self.f:
                    m_.AddImplication(v, self.f[sid[0]].Not())
        n_dropped = sum(len(dl) for sid, dl in cand.items() if sid not in self.slots)
        log(f"support x : hint {nA}, +pool {nA2}, +libres {nB}, +petits {nC} ; créés {len(self.x)} "
            f"(paires de créneaux inexistants ignorées {n_dropped}) ; créneaux {len(self.slots)}")
        self.by_s = by_s
        # ---- contraintes ----
        for d, vs in by_d.items():
            if len(vs) > 1:
                m_.AddAtMostOne(vs)
        n_empty = 0
        for sid, s in self.slots.items():
            terms = by_s.get(sid, [])
            expr = sum(sz * v for sz, v in terms) if terms else 0
            if s["act"] is None:
                if not terms:
                    n_empty += 1
                    continue
                m_.Add(expr >= s["lb"])
                m_.Add(expr <= s["ub"])
            else:
                if not terms:
                    m_.Add(s["act"] == 0)
                    n_empty += 1
                    continue
                m_.Add(expr >= s["lb"] * s["act"])
                m_.Add(expr <= s["ub"] * s["act"])
        if n_empty:
            log(f"ATTENTION : {n_empty} créneaux sans candidat")
        # générateurs / cibles par type
        self.gen_fixed = Counter()
        self.tgt_fixed = Counter()
        for m in range(nm):
            if m in free or self.hint_role[m] is None:
                continue
            r = self.hint_role[m]
            if r[0] == "Y":
                self.gen_fixed[inst.reqs[m][0][0]] += 1
            elif r[0] == "H":
                for t in r[1]:
                    self.tgt_fixed[t] += 1
        for t in range(4):
            gens = [self.y[m] for m in self.y if inst.reqs[m][0][0] == t]
            tg = [self.z[(m, tt)] for (m, tt) in self.z if tt == t]
            m_.Add(sum(tg) + self.tgt_fixed[t] <= sum(gens) + self.gen_fixed[t])
        # énergie
        e_fixed = sum(inst.energy[m] for m in range(nm) if m not in free and self.hint_role[m] is not None)
        e_terms = []
        for m in free:
            for v in (self.f.get(m), self.h.get(m), self.y.get(m)):
                if v is not None:
                    e_terms.append(inst.energy[m] * v)
        m_.Add(sum(e_terms) <= inst.cap - e_fixed)
        self.e_fixed = e_fixed
        # objectif
        self.v_fixed = 0
        obj = []
        for m in range(nm):
            if m in free:
                if m in self.f:
                    obj.append(inst.value[m] * self.f[m])
                obj.append((inst.value[m] // 2) * self.h[m])
            elif self.hint_role[m] is not None:
                if self.hint_role[m][0] == "F":
                    self.v_fixed += inst.value[m]
                elif self.hint_role[m][0] == "H":
                    self.v_fixed += inst.value[m] // 2
        m_.Maximize(sum(obj) + self.v_fixed)
        # symétries : datasets identiques (type, taille, copyright) avec le même support -> ordre d'utilisation
        sig = defaultdict(list)
        for d in by_d:
            key = (inst.ds[d], tuple(sorted(sids_of_d[d])))
            sig[key].append(d)
        nsym = 0
        hinted = {d for d, _ in hint_sol["dataMappings"]}
        for key, dl in sig.items():
            if len(dl) < 2:
                continue
            dl.sort(key=lambda d: (d not in hinted, d))
            for d1, d2 in zip(dl, dl[1:]):
                m_.Add(sum(by_d[d1]) >= sum(by_d[d2]))
                nsym += 1
        self.by_d = by_d
        log(f"contraintes de symétrie (datasets jumeaux) : {nsym} ; énergie fixée {e_fixed / inst.cap:.6f} cap ; "
            f"valeur fixée {self.v_fixed}")
        self.set_hint(hint_sol)

    def set_hint(self, sol):
        m_, inst = self.m, self.inst
        m_.ClearHints()
        role, packs = roles_of(inst, sol)
        for m in self.free:
            r = role[m]
            if m in self.f:
                m_.AddHint(self.f[m], 1 if r is not None and r[0] == "F" else 0)
            m_.AddHint(self.h[m], 1 if r is not None and r[0] == "H" else 0)
            if m in self.y:
                m_.AddHint(self.y[m], 1 if r is not None and r[0] == "Y" else 0)
            for t, _, _ in inst.reqs[m]:
                m_.AddHint(self.z[(m, t)], 1 if r is not None and r[0] == "H" and t in r[1] else 0)
        for (d, sid), v in self.x.items():
            m_.AddHint(v, 1 if d in packs.get(sid, ()) else 0)

    def decode(self, val):
        """val : fonction variable -> valeur. Retourne (solution json, énergie)."""
        inst = self.inst
        nm = len(inst.value)
        role = list(self.hint_role)
        for m in self.free:
            if m in self.f and val(self.f[m]):
                role[m] = ("F",)
            elif val(self.h[m]):
                role[m] = ("H", frozenset(t for t, _, _ in inst.reqs[m] if val(self.z[(m, t)])))
            elif m in self.y and val(self.y[m]):
                role[m] = ("Y",)
            else:
                role[m] = None
        dm = []
        for (d, sid), v in self.x.items():
            if val(v):
                dm.append([d, sid[0]])
        if self.type is not None:
            dm.extend([d, m] for d, m in self.hint_dm if inst.ds[d][0] != self.type)
        gens = defaultdict(list)
        tg = defaultdict(list)
        for m in range(nm):
            r = role[m]
            if r is None:
                continue
            if r[0] == "Y":
                gens[inst.reqs[m][0][0]].append(m)
            elif r[0] == "H":
                for t in r[1]:
                    tg[t].append(m)
        mm = []
        drop = set()
        for t in range(4):
            if len(tg[t]) > len(gens[t]):
                raise RuntimeError(f"type {t}: {len(tg[t])} cibles > {len(gens[t])} générateurs")
            for g, m in zip(gens[t], tg[t]):
                mm.append([g, m])
            for g in gens[t][len(tg[t]):]:
                drop.add(g)
        if drop:
            dm = [[d, m] for d, m in dm if m not in drop]
        return {"dataMappings": [[int(d), int(m)] for d, m in sorted(dm)], "modelMappings": [[int(g), int(m)] for g, m in mm]}


class Callback:
    def __init__(self, model, k, tag, method, best_known, t0):
        from ortools.sat.python import cp_model
        super_ = cp_model.CpSolverSolutionCallback
        self.cb = type("CB", (super_,), {})()
        self.model, self.k, self.tag, self.method, self.best, self.t0 = model, k, tag, method, best_known, t0
        self.best_sol = None
        self.n = 0
        cb = self

        def on_solution_callback(self_):
            cb.on_sol(self_)
        type(self.cb).on_solution_callback = on_solution_callback

    def on_sol(self, s):
        self.n += 1
        obj = int(round(s.ObjectiveValue()))
        if obj <= self.best:
            if self.n <= 3 or self.n % 20 == 0:
                log(f"  sol {self.n}: obj {obj} (<= {self.best}) borne {s.BestObjectiveBound():.0f} t={time.time() - self.t0:.0f}s")
            return
        try:
            sol = self.model.decode(lambda v: s.Value(v))
        except Exception as e:
            log(f"  sol {self.n}: obj {obj} décodage impossible : {e}")
            return
        txt = json.dumps(sol, separators=(",", ":"))
        score, ok, msg = evaluate(self.k, txt, self.model.inst.txt)
        log(f"  sol {self.n}: obj {obj} -> score officiel {score} valide={ok} {msg} borne {s.BestObjectiveBound():.0f} "
            f"t={time.time() - self.t0:.0f}s")
        if ok and score == obj and score > self.best:
            self.best = score
            self.best_sol = sol
            path = os.path.join(ROOT, "runs", f"m10_{self.tag}_best.json")
            with open(path, "w") as f:
                f.write(txt)
            r = subprocess.run([sys.executable, os.path.join(ROOT, "src", "save_if_better.py"), str(self.k), path,
                                "--method", f"m10 {self.method}"], capture_output=True, text=True)
            log(f"  save_if_better rc={r.returncode} {r.stdout.strip()}")
        elif ok and score != obj:
            log(f"  INCOHÉRENCE objectif {obj} != score {score}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("k", type=int)
    ap.add_argument("--pool", default="runs/m10_pool/*.json")
    ap.add_argument("--hint", default=None)
    ap.add_argument("--lpk", type=int, default=150, help="modèles inutilisés libérés par rôle (meilleur coût réduit LP)")
    ap.add_argument("--targets", type=int, default=100, help="cibles demi-tarif libérées (bascule h->f)")
    ap.add_argument("--worst", type=int, default=50, help="modèles pleins / générateurs au pire coût réduit libérés")
    ap.add_argument("--small", type=int, default=0, help="datasets de taille <= small candidats partout")
    ap.add_argument("--full-free", action="store_true")
    ap.add_argument("--time", type=float, default=600)
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tag", default="t")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--type", type=int, default=None, help="restreindre le modèle au type t (modèles mono-type t libres)")
    ap.add_argument("--fix-hint", action="store_true")
    ap.add_argument("--log-search", action="store_true")
    ap.add_argument("--method", default="")
    a = ap.parse_args()
    t0 = time.time()
    inst = Instance(a.k)
    hint_path = a.hint or os.path.join(ROOT, "best", f"instance_{a.k}.json")
    hint_sol = json.load(open(hint_path))
    pool = []
    for p in sorted(glob.glob(os.path.join(ROOT, a.pool) if not os.path.isabs(a.pool) else a.pool)):
        if os.path.abspath(p) == os.path.abspath(hint_path):
            continue
        s = json.load(open(p))
        sc, ok, _ = evaluate(a.k, json.dumps(s), inst.txt)
        if ok:
            pool.append(s)
    ref = evaluate(a.k, json.dumps(hint_sol), inst.txt)[0]
    log(f"m10_cp k={a.k} hint {hint_path} = {ref}, pool {len(pool)} solutions valides")
    M = Model(inst, hint_sol, pool, a)
    log(f"modèle construit en {time.time() - t0:.0f}s : vars x {len(M.x)}, rôles f/h/y {len(M.f)}/{len(M.h)}/{len(M.y)}, z {len(M.z)}")
    if a.stats:
        return
    from ortools.sat.python import cp_model
    method = a.method or f"{a.tag} lpk={a.lpk} tg={a.targets} small={a.small}{' ff' if a.full_free else ''} seed={a.seed}"
    cb = Callback(M, a.k, a.tag, method, ref, t0)
    cur = hint_sol
    for r in range(a.rounds):
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = a.time
        solver.parameters.num_workers = a.workers
        solver.parameters.random_seed = a.seed + r
        solver.parameters.log_search_progress = a.log_search
        if a.fix_hint:
            solver.parameters.fix_variables_to_their_hinted_value = True
        M.set_hint(cur)
        log(f"tour {r + 1}/{a.rounds} : solve {a.time:.0f}s, {a.workers} workers, seed {a.seed + r}, hint {cb.best}")
        st = solver.Solve(M.m, cb.cb)
        log(f"tour {r + 1} : {solver.StatusName(st)} obj {solver.ObjectiveValue():.0f} borne {solver.BestObjectiveBound():.0f} "
            f"wall {solver.WallTime():.0f}s ; meilleur validé {cb.best} (hint {ref})")
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            break
        if a.fix_hint:
            sol = M.decode(lambda v: solver.Value(v))
            sc, ok, msg = evaluate(a.k, json.dumps(sol), inst.txt)
            log(f"décodage hint fixé : score {sc} valide={ok} {msg} (attendu {ref})")
            break
        if cb.best_sol is not None:
            cur = cb.best_sol
        if st == cp_model.OPTIMAL:
            break
    log(f"FIN m10_cp {a.tag} : meilleur {cb.best} (hint {ref}), {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
