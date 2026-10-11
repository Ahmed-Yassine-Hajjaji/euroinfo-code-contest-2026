#!/usr/bin/env python3
"""Sous-processus CP-SAT du RINS m9 (ortools et highspy ne cohabitent pas dans un même processus).

Lit un MIP réduit (npz écrit par m9_rins_cp.py : matrice csc des colonnes libres, bornes de lignes déjà diminuées de
l'activité des colonnes fixées, objectif entier à minimiser, hint 0/1), le résout avec CP-SAT (toutes variables
booléennes, lignes à coefficients entiers ou mises à l'échelle 1e9), écrit la solution dans un npz.
Usage : python src/m9_rins_cp_solve.py in.npz out.npz --workers 8 --time 900 --seed 1
"""
import argparse
import sys
import time

import numpy as np
from ortools.sat.python import cp_model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp"); ap.add_argument("out")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--time", type=float, default=900)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--log", type=int, default=0)
    a = ap.parse_args()
    t0 = time.time()
    z = np.load(a.inp)
    indptr, indices, data = z["indptr"], z["indices"], z["data"]
    rlo, rhi, obj, hint = z["rlo"], z["rhi"], z["obj"], z["hint"]
    n = len(obj); nr = len(rlo)
    # passage en lignes
    from scipy.sparse import csc_matrix
    A = csc_matrix((data, indices, indptr), shape=(nr, n)).tocsr()
    m = cp_model.CpModel()
    x = [m.NewBoolVar(f"x{j}") for j in range(n)]
    nrows = 0; nscaled = 0; ndrop = 0
    for i in range(nr):
        s, e = A.indptr[i], A.indptr[i + 1]
        if s == e:
            # ligne sans colonne libre : faisabilité déjà vérifiée côté parent
            continue
        cols = A.indices[s:e]; vals = A.data[s:e]
        lo_, hi_ = float(rlo[i]), float(rhi[i])
        if np.max(np.abs(vals - np.round(vals))) > 1e-9:
            vals = np.round(vals * 1e9); lo_ = lo_ * 1e9; hi_ = hi_ * 1e9; nscaled += 1
        else:
            vals = np.round(vals)
        ivals = vals.astype(np.int64)
        lo_i = -cp_model.INT32_MAX * 4 if lo_ == -np.inf else int(np.ceil(lo_ - 1e-6))
        hi_i = cp_model.INT32_MAX * 4 if hi_ == np.inf else int(np.floor(hi_ + 1e-6))
        pos = int(np.sum(ivals[ivals > 0])); neg = int(np.sum(ivals[ivals < 0]))
        if lo_i <= neg and hi_i >= pos:
            ndrop += 1; continue  # ligne toujours satisfaite
        m.Add(sum(int(v) * x[j] for v, j in zip(ivals.tolist(), cols.tolist())) >= lo_i) if lo_i > neg else None
        m.Add(sum(int(v) * x[j] for v, j in zip(ivals.tolist(), cols.tolist())) <= hi_i) if hi_i < pos else None
        nrows += 1
    iobj = np.round(obj).astype(np.int64)
    nz = np.nonzero(iobj)[0]
    if len(nz):
        m.Minimize(sum(int(iobj[j]) * x[j] for j in nz.tolist()))
    for j in range(n):
        m.AddHint(x[j], int(hint[j] > 0.5))
    print(f"[cp] {n} variables, {nrows} lignes ({nscaled} mises à l'échelle, {ndrop} triviales), objectif sur {len(nz)} var., "
          f"construction {time.time() - t0:.0f}s", flush=True)
    s = cp_model.CpSolver()
    s.parameters.num_workers = a.workers
    s.parameters.max_time_in_seconds = a.time
    s.parameters.random_seed = a.seed
    s.parameters.log_search_progress = bool(a.log)
    s.parameters.fix_variables_to_their_hinted_value = False
    t1 = time.time()
    st = s.Solve(m)
    name = s.StatusName(st)
    ok = st in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    xs = np.array([s.Value(v) for v in x], float) if ok else np.zeros(n)
    val = float(s.ObjectiveValue()) if ok else np.nan
    bnd = float(s.BestObjectiveBound()) if st != cp_model.UNKNOWN or True else np.nan
    np.savez(a.out, x=xs, status=name, ok=ok, obj=val, bound=bnd, time=time.time() - t1)
    print(f"[cp] {name} en {time.time() - t1:.0f}s : objectif {val} borne {bnd}", flush=True)


if __name__ == "__main__":
    main()
