"""Réparation exacte CP-SAT d'un sous-problème (un type de données t) pour le LNS.

Emplacements = besoins de type t remplis par des datasets (modèles entraînés) + générateurs de type t,
plus des mono-modèles inutilisés de type t (option plein tarif : libres seuls ; option demi-tarif : tout).
On libère leurs datasets (+ ceux encore disponibles du type t) et on réaffecte :
  max  W·valeur − gaspillage,  chaque dataset ≤ 1 emplacement, lb·y ≤ somme ≤ ub·y, énergie.
Supprimer un emplacement existant = retirer son modèle propriétaire (et ses générateurs) : perte de sa valeur,
gain de son énergie. La solution courante est donnée en hint : la valeur ne peut pas baisser.
"""
from ortools.sat.python import cp_model

W = 10_000_000  # poids de la valeur devant le gaspillage (gaspillage d'un sous-problème << W)


def cp_move(st, rng, n_slots=60, n_new=30, n_pool=300, tlimit=2.0, workers=1, t=None):
    inst = st.inst
    if t is None:
        t = rng.randrange(4)
    # ---- emplacements existants ----
    slots = []  # dict(owner, g, lb, ub, free_only, dl, val, efree)
    for m, entries in st.assign.items():
        for tt, dl, g in entries:
            if tt != t:
                continue
            val = st.model_value(m, entries)
            efree = inst.energy[m] + sum(inst.energy[gg] for _, _, gg in entries if gg >= 0)
            if g < 0:
                _, lb, ub = next(r for r in inst.reqs[m] if r[0] == t)
                slots.append(dict(owner=m, g=-1, lb=lb, ub=ub, free_only=(val == inst.value[m] and val > 0),
                                  dl=dl, val=val, efree=efree))
            else:
                _, lb, ub = inst.reqs[g][0]
                slots.append(dict(owner=m, g=g, lb=lb, ub=ub, free_only=False, dl=st.gdata[g], val=val,
                                  efree=efree))
    if not slots:
        return None
    # biais vers les emplacements qui gaspillent
    w = [sum(x[0] for x in s["dl"]) - s["lb"] + 1 for s in slots]
    chosen = []
    idx = list(range(len(slots)))
    if len(idx) > n_slots:
        # tirage pondéré sans remise (clé exponentielle)
        idx.sort(key=lambda i: -rng.random() ** (1.0 / w[i]))
        idx = idx[:n_slots]
    chosen = [slots[i] for i in idx]
    owners = {s["owner"] for s in chosen}
    if len(owners) != len(chosen):  # sécurité : un propriétaire = un emplacement de type t
        return None
    # ---- datasets ----
    D = {}
    for s in chosen:
        for x in s["dl"]:
            D[x[1]] = x
    pool = st.pools.p[t][0] + st.pools.p[t][1]
    pool = [(sz, i, inst.ds[i][2]) for sz, i in pool]
    if len(pool) > n_pool:
        pool = rng.sample(pool, n_pool)
    for x in pool:
        D[x[1]] = x
    Dl = list(D.values())
    # ---- nouveaux candidats : mono-modèles inutilisés de type t ----
    e_left = inst.cap - st.energy
    max_e = e_left + sum(s["efree"] for s in chosen)
    cands = [m for m in range(len(inst.value)) if st.used[m] == 0 and inst.gen_ok[m]
             and inst.reqs[m][0][0] == t and inst.energy[m] <= max_e]
    cands.sort(key=lambda m: -inst.value[m] / (inst.reqs[m][0][1] + 1))
    cands = cands[:3 * n_new]
    news = rng.sample(cands, min(n_new, len(cands)))

    # ---- modèle CP-SAT ----
    md = cp_model.CpModel()
    J = []  # (kind, ref, lb, ub, free_only, val)
    for s in chosen:
        J.append(("old", s, s["lb"], s["ub"], s["free_only"], s["val"]))
    for m in news:
        _, lb, ub = inst.reqs[m][0]
        J.append(("full", m, lb, ub, True, inst.value[m]))
        J.append(("half", m, lb, ub, False, inst.value[m] // 2))
    y = [md.NewBoolVar(f"y{j}") for j in range(len(J))]
    x = {}
    by_d = {}
    for j, (_, _, lb, ub, fo, _) in enumerate(J):
        terms = []
        for sz, i, c in Dl:
            if sz <= ub and not (fo and c):
                v = md.NewBoolVar("")
                x[(i, j)] = v
                by_d.setdefault(i, []).append(v)
                terms.append(sz * v)
        md.Add(sum(terms) >= lb * y[j]) if terms else md.Add(y[j] == 0)
        if terms:
            md.Add(sum(terms) <= ub * y[j])
    for vs in by_d.values():
        if len(vs) > 1:
            md.AddAtMostOne(vs)
    jn = 0
    for m in news:  # plein OU demi
        base = len(chosen) + 2 * jn
        md.AddAtMostOne([y[base], y[base + 1]])
        jn += 1
    # énergie
    e_terms = []
    const = 0
    for j, (kind, ref, *_r) in enumerate(J):
        if kind == "old":
            e_terms.append(ref["efree"] * y[j])
            const += ref["efree"]
        else:
            e_terms.append(inst.energy[ref] * y[j])
    md.Add(sum(e_terms) <= e_left + const)
    # objectif : W·valeur − gaspillage
    obj = []
    size = {i: sz for sz, i, _ in Dl}
    for j, (_, _, lb, _, _, val) in enumerate(J):
        obj.append((W * val + lb) * y[j])
    for (i, j), v in x.items():
        obj.append(-size[i] * v)
    md.Maximize(sum(obj))
    # hint = solution courante
    cur = {}
    for j, s in enumerate(chosen):
        for xx in s["dl"]:
            cur[xx[1]] = j
    for (i, j), v in x.items():
        md.AddHint(v, 1 if cur.get(i) == j else 0)
    for j in range(len(J)):
        md.AddHint(y[j], 1 if j < len(chosen) else 0)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tlimit
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = rng.randrange(1 << 30)
    status = solver.Solve(md)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    old_val = sum(s["val"] for s in chosen)
    old_w = sum(sum(xx[0] for xx in s["dl"]) - s["lb"] for s in chosen)
    new_val = sum(J[j][5] for j in range(len(J)) if solver.Value(y[j]))
    new_dl = [[] for _ in J]
    for (i, j), v in x.items():
        if solver.Value(v):
            new_dl[j].append(D[i])
    new_w = sum(sum(xx[0] for xx in new_dl[j]) - J[j][2] for j in range(len(J)) if solver.Value(y[j]))
    if (new_val, -new_w) <= (old_val, -old_w):
        return None  # rien de mieux (valeur, puis gaspillage)
    # ---- application ----
    recs = {s["owner"]: st.remove(s["owner"]) for s in chosen}
    for j, s in enumerate(chosen):
        if not solver.Value(y[j]):
            continue
        m, entries, gens = recs[s["owner"]]
        if s["g"] < 0:
            entries = [(tt, new_dl[j] if tt == t else dl, g) for tt, dl, g in entries]
        else:
            gens = dict(gens)
            gens[s["g"]] = new_dl[j]
        st.apply(m, entries, gens)
    for j in range(len(chosen), len(J)):
        if solver.Value(y[j]):
            st.apply(J[j][1], [(t, new_dl[j], -1)], {})
    return dict(t=t, old_val=old_val, new_val=new_val, old_w=old_w, new_w=new_w,
                dropped=[s["owner"] for j, s in enumerate(chosen) if not solver.Value(y[j])],
                status=solver.StatusName(status))
