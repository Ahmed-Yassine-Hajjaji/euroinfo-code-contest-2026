"""Empaquetage exact par type (CP-SAT, niveau dataset) : affecte les datasets d'un type à des créneaux (lb, ub)
en maximisant le poids des créneaux remplis, puis en minimisant la consommation (lexicographique approché).
Un créneau = (id, lb, ub, poids, pools autorisés (0 libre / 1 copyr)). Utilisé par mip6.py (étape C)."""
import time
from ortools.sat.python import cp_model


def pack(datasets, slots, tlimit=60.0, workers=4, hint=None, groups=None, eps=1e-3, log=False):
    """datasets : liste de (id, size, copyr) d'un même type ; slots : liste de (sid, lb, ub, w, allow_cr).
    groups : {gid: [slot index, ...]} créneaux liés (même modèle multi-type) : tous actifs ou aucun (poids porté
    par le groupe, w des créneaux ignoré). hint : {sid: [dataset id, ...]} solution de départ.
    Retourne (assign {sid: [dataset id]}, active {sid: bool}, status, obj)."""
    m = cp_model.CpModel()
    x = {}
    act = {}
    for j, (sid, lb, ub, w, allow_cr) in enumerate(slots):
        act[j] = m.NewBoolVar(f"a{j}")
        terms = []
        for i, (did, s, c) in enumerate(datasets):
            if (c and not allow_cr) or s > ub:
                continue
            v = m.NewBoolVar(f"x{i}_{j}")
            x[(i, j)] = v
            terms.append(s * v)
        if not terms:
            m.Add(act[j] == 0)
            continue
        m.Add(sum(terms) >= lb * act[j])
        m.Add(sum(terms) <= ub * act[j])
    for i in range(len(datasets)):
        vs = [x[(i, j)] for j in range(len(slots)) if (i, j) in x]
        if vs:
            m.AddAtMostOne(vs)
    obj = []
    gw = {}
    if groups:
        for gid, js in groups.items():
            gv = m.NewBoolVar(f"g{gid}")
            for j in js[0]:
                m.Add(act[j] == gv)
            obj.append(js[1] * gv)
            gw[gid] = gv
        ingroup = {j for js in groups.values() for j in js[0]}
    else:
        ingroup = set()
    for j, (sid, lb, ub, w, _) in enumerate(slots):
        if j not in ingroup:
            obj.append(w * act[j])
    # second critère : consommation minimale (eps par unité, << 1 point)
    cons = sum(datasets[i][1] * v for (i, j), v in x.items())
    m.Maximize(sum(obj) * 1000 - cons * max(1, int(eps * 1000)) if eps else sum(obj))
    if hint:
        idx = {did: i for i, (did, _, _) in enumerate(datasets)}
        sidx = {sid: j for j, (sid, *_r) in enumerate(slots)}
        for sid, dl in hint.items():
            if sid in sidx:
                j = sidx[sid]
                hinted = set()
                for did in dl:
                    if did in idx and (idx[did], j) in x:
                        m.AddHint(x[(idx[did], j)], 1); hinted.add(idx[did])
                m.AddHint(act[j], 1 if dl else 0)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tlimit
    solver.parameters.num_workers = workers
    solver.parameters.log_search_progress = log
    t0 = time.time()
    st = solver.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, None, solver.StatusName(st), None
    assign, active = {}, {}
    for j, (sid, *_r) in enumerate(slots):
        active[sid] = bool(solver.Value(act[j]))
        assign[sid] = [datasets[i][0] for (i, jj), v in x.items() if jj == j and solver.Value(v)]
    return assign, active, solver.StatusName(st), (solver.ObjectiveValue(), solver.BestObjectiveBound(), time.time() - t0)


if __name__ == "__main__":
    # test : créneaux F (plein tarif) d'un type pour les rôles runs/mipr_k.json, datasets libres du type
    import json, os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from greedy import Instance
    k, t, T, W = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4])
    roles = sys.argv[5] if len(sys.argv) > 5 else f"runs/mipr_{k}.json"
    inst = Instance(k); ro = json.load(open(roles))
    ds = [(d, s, c) for d, (tt, s, c) in enumerate(inst.ds) if tt == t and not c]
    slots = []; groups = {}
    for m_ in range(len(inst.value)):
        if ro["f"][m_] > 0.5:
            for tt, lb, ub in inst.reqs[m_]:
                if tt == t:
                    slots.append(((m_, t), lb, ub, inst.value[m_] / len(inst.reqs[m_]), False))
    # hint : best/
    best = json.load(open(f"best/instance_{k}.json"))
    hint = {}
    for d, m_ in best["dataMappings"]:
        if inst.ds[d][0] == t:
            hint.setdefault((m_, t), []).append(d)
    print(f"type {t}: {len(ds)} datasets libres (Σ {sum(s for _, s, _ in ds)}), {len(slots)} créneaux F (Σ lb {sum(s[1] for s in slots)})", flush=True)
    a, act, status, obj = pack(ds, slots, tlimit=T, workers=W, hint=hint, log=True)
    if a is None:
        print("échec", status); sys.exit(1)
    nact = sum(act.values()); cons = sum(inst.ds[d][1] for dl in a.values() for d in dl)
    lbs = sum(lb for (sid, lb, ub, w, _) in slots if act[sid])
    print(f"status {status} obj {obj} : créneaux actifs {nact}/{len(slots)} ; consommation {cons} ; Σ lb actifs {lbs} ; gaspillage {cons-lbs}")
