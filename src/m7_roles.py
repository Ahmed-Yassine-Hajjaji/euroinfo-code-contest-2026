#!/usr/bin/env python3
"""m7 — LP/MIP des rôles (f/h/y/z) avec highspy, coûts réduits, candidats par seuil.
Relaxation valide : lb compté comme consommation ; données libres (f) et totales (f+h+y) par type ; énergie ;
générateurs par type. Utilisé par m7_stats.py et m7_mip.py.
"""
import json
import os
import sys

import numpy as np
from scipy.sparse import coo_matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402


class Roles:
    def __init__(self, inst):
        self.inst = inst
        nm = len(inst.value)
        self.F = [0] * 4; self.C = [0] * 4
        for t, s, c in inst.ds:
            (self.C if c else self.F)[t] += s
        self.T = [self.F[t] + self.C[t] for t in range(4)]
        col = 0
        self.fi, self.hi, self.yi, self.zi = {}, {}, {}, {}
        obj, ub = [], []
        for m in range(nm):
            feas = all(lb <= u for _, lb, u in inst.reqs[m])
            self.fi[m] = col; obj.append(-inst.value[m]); ub.append(1.0 if feas else 0.0); col += 1
            self.hi[m] = col; obj.append(-(inst.value[m] // 2)); ub.append(1.0); col += 1
            if inst.gen_ok[m]:
                self.yi[m] = col; obj.append(0.0); ub.append(1.0); col += 1
            for t, lb, u in inst.reqs[m]:
                self.zi[(m, t)] = col; obj.append(0.0); ub.append(1.0); col += 1
        rows, cols, vals, rhs = [], [], [], []
        r = 0
        self.R_E = r
        for m in range(nm):
            e = inst.energy[m] / inst.cap
            for c in (self.fi[m], self.hi[m]) + ((self.yi[m],) if m in self.yi else ()):
                rows.append(r); cols.append(c); vals.append(e)
        rhs.append(1.0); r += 1
        self.R_F = list(range(r, r + 4)); r += 4
        self.R_T = list(range(r, r + 4)); r += 4
        self.R_G = list(range(r, r + 4)); r += 4
        rhs += [self.F[t] / max(self.T[t], 1) for t in range(4)] + [1.0] * 4 + [0.0] * 4
        for m in range(nm):
            for t, lb, u in inst.reqs[m]:
                a = lb / max(self.T[t], 1)
                rows += [self.R_F[t], self.R_T[t], self.R_T[t], self.R_T[t]]
                cols += [self.fi[m], self.fi[m], self.hi[m], self.zi[(m, t)]]
                vals += [a, a, a, -a]
                rows.append(self.R_G[t]); cols.append(self.zi[(m, t)]); vals.append(1.0)
            if m in self.yi:
                t, lb, _ = inst.reqs[m][0]
                rows += [self.R_T[t], self.R_G[t]]; cols += [self.yi[m], self.yi[m]]; vals += [lb / max(self.T[t], 1), -1.0]
        for m in range(nm):
            rows += [r, r]; cols += [self.fi[m], self.hi[m]]; vals += [1.0, 1.0]
            if m in self.yi:
                rows.append(r); cols.append(self.yi[m]); vals.append(1.0)
            rhs.append(1.0); r += 1
            for t, lb, u in inst.reqs[m]:
                rows += [r, r]; cols += [self.zi[(m, t)], self.hi[m]]; vals += [1.0, -1.0]; rhs.append(0.0); r += 1
                if lb > u:
                    rows += [r, r]; cols += [self.hi[m], self.zi[(m, t)]]; vals += [1.0, -1.0]; rhs.append(0.0); r += 1
        self.A = coo_matrix((vals, (rows, cols)), shape=(r, col)).tocsc()
        self.obj = np.array(obj); self.ub = np.array(ub); self.rhs = np.array(rhs)
        self.ncol = col

    def solve(self, integer=False, time_limit=60, threads=4, hint=None, lo=None, ub=None, verbose=False, shrink=None):
        """shrink : liste de 4 quantités (unités) retirées de l'offre LIBRE par type (gaspillage anticipé)."""
        import highspy
        rhs = self.rhs.copy()
        if shrink is not None:
            for t in range(4):
                rhs[self.R_F[t]] = (self.F[t] - shrink[t]) / max(self.T[t], 1)
        h = highspy.Highs()
        h.setOptionValue("output_flag", verbose)
        h.setOptionValue("threads", threads)
        lp = highspy.HighsLp()
        lp.num_col_ = self.ncol; lp.num_row_ = len(self.rhs)
        lp.col_cost_ = self.obj
        lp.col_lower_ = np.zeros(self.ncol) if lo is None else lo
        lp.col_upper_ = self.ub if ub is None else ub
        lp.row_lower_ = np.full(len(self.rhs), -np.inf); lp.row_upper_ = rhs
        lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
        lp.a_matrix_.start_ = self.A.indptr.astype(np.int32); lp.a_matrix_.index_ = self.A.indices.astype(np.int32)
        lp.a_matrix_.value_ = self.A.data
        if integer:
            lp.integrality_ = [highspy.HighsVarType.kInteger] * self.ncol
        h.passModel(lp)
        if integer:
            h.setOptionValue("time_limit", float(time_limit)); h.setOptionValue("mip_rel_gap", 0.0)
            if hint is not None:
                s0 = highspy.HighsSolution(); s0.col_value = list(hint); h.setSolution(s0)
        h.run()
        s = h.getSolution()
        x = np.array(s.col_value)
        out = {"x": x, "value": float(-self.obj @ x), "status": h.modelStatusToString(h.getModelStatus())}
        if integer:
            out["bound"] = float(-h.getInfo().mip_dual_bound)
        else:
            out["rc"] = np.array(s.col_dual); out["dual"] = -np.array(s.row_dual); out["bound"] = float(-h.getInfo().objective_function_value)
        return out

    def roles_of_solution(self, sol):
        """x (vecteur de rôles) d'une solution JSON."""
        inst = self.inst
        x = np.zeros(self.ncol)
        src = {s for s, _ in sol["modelMappings"]}
        cp = {}
        for d, m in sol["dataMappings"]:
            cp[m] = cp.get(m, False) or bool(inst.ds[d][2])
        tg = {}
        for s, t in sol["modelMappings"]:
            tg.setdefault(t, []).append(inst.reqs[s][0][0])
        for m in set(cp) | src | set(tg):
            if m in src:
                x[self.yi[m]] = 1
            elif cp.get(m) or m in tg:
                x[self.hi[m]] = 1
                for t in tg.get(m, []):
                    x[self.zi[(m, t)]] = 1
            else:
                x[self.fi[m]] = 1
        return x


if __name__ == "__main__":
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    inst = Instance(k)
    R = Roles(inst)
    sol = json.load(open(os.path.join(ROOT, "best", f"instance_{k}.json")))
    x0 = R.roles_of_solution(sol)
    lp = R.solve()
    print("borne LP", lp["bound"], "valeur rôles best", float(-R.obj @ x0))
    rc = lp["rc"]; xl = lp["x"]
    nm_ = len(inst.value)
    for thr in (30, 50, 77, 100, 150, 250, 500):
        nf = sum(1 for m in range(nm_) if R.ub[R.fi[m]] > 0 and (xl[R.fi[m]] > 1e-9 or rc[R.fi[m]] <= thr))
        nh = sum(1 for m in range(nm_) if xl[R.hi[m]] > 1e-9 or rc[R.hi[m]] <= thr)
        ny = sum(1 for m in R.yi if xl[R.yi[m]] > 1e-9 or rc[R.yi[m]] <= thr)
        # créneaux f candidats par type
        slots = [0] * 4
        for m in range(nm_):
            if R.ub[R.fi[m]] > 0 and (xl[R.fi[m]] > 1e-9 or rc[R.fi[m]] <= thr):
                for t, lb, u in inst.reqs[m]:
                    slots[t] += 1
        print(f"seuil rc {thr}: f-candidats {nf}, h-candidats {nh}, y-candidats {ny}, créneaux f par type {slots}")
    # best : rc des rôles de best hors LP
    fb = [m for m in range(len(inst.value)) if x0[R.fi[m]] > 0.5]
    print("f dans best", len(fb), "dont rc>77 :", sum(1 for m in fb if xl[R.fi[m]] < 1e-9 and rc[R.fi[m]] > 77))
    hb = [m for m in range(len(inst.value)) if x0[R.hi[m]] > 0.5]
    print("h dans best", len(hb), "dont rc>77 :", sum(1 for m in hb if xl[R.hi[m]] < 1e-9 and rc[R.hi[m]] > 77))
    print("frac LP", int(((xl > 1e-6) & (xl < 1 - 1e-6)).sum()))
    print("prix duaux : énergie", lp["dual"][R.R_E], "libres/unité", [lp["dual"][R.R_F[t]] / R.T[t] for t in range(4)],
          "totales", [lp["dual"][R.R_T[t]] / R.T[t] for t in range(4)], "gen", [lp["dual"][R.R_G[t]] for t in range(4)])
