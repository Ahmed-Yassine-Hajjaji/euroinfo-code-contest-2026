#!/usr/bin/env python3
"""Méthode 4 bis : chaînes d'échanges exactes (BFS) pour libérer des datasets entiers, à rôles fixés.

Structure du mouvement (la seule qui réduise le nombre de datasets affectés quand aucun retrait direct n'existe) :
un créneau M à >= 2 datasets donne deux de ses membres x et y et reçoit un dataset w ; y part dans le pool libre
(ou, variante, y remplace le dataset d'un créneau P dont le dataset est libéré) ; w vient d'un créneau W qui reçoit
le dataset d'un créneau suivant, etc. ; la chaîne se termine par un créneau qui reçoit x. Chaque créneau de la chaîne
donne un dataset et en reçoit un, dans sa fenêtre [lb, ub] (et libre seulement si plein tarif). La chaîne est trouvée
par BFS (longueur minimale) dans le graphe « u reçoit le dataset de v » restreint au type ; les créneaux sont distincts.
Glouton : à chaque itération, le mouvement qui libère le plus (taille pondérée par les prix duaux LP), puis mise à jour.

Usage : python src/m4_chain.py <k> <sol_in> <sol_out> [--maxlen 12] [--time 300] [--types 0,1,2,3] [--minfree 1]
"""
import argparse
import json
import os
import sys
import time
from bisect import bisect_left, bisect_right
from collections import deque

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from greedy import Instance  # noqa: E402
from m3_prep import slots_of  # noqa: E402  (lecture seule)
from save_if_better import evaluate  # noqa: E402


class Type:
    """Structures d'un type : créneaux, membres, sommes, nœuds (= datasets affectés) triés par taille."""

    def __init__(self, inst, slots, assign, t):
        self.inst, self.slots, self.assign, self.t = inst, slots, assign, t
        self.members = {}
        for d, s in enumerate(assign):
            if s >= 0 and inst.ds[d][0] == t:
                self.members.setdefault(s, []).append(d)
        self.rebuild()

    def rebuild(self):
        inst, slots = self.inst, self.slots
        self.sum = {s: sum(inst.ds[d][1] for d in ds) for s, ds in self.members.items()}
        nodes = []
        for s, ds in self.members.items():
            for d in ds:
                nodes.append((inst.ds[d][1], d))
        nodes.sort()
        self.sizes = [sz for sz, _ in nodes]
        self.nodes = [d for _, d in nodes]

    def window_after_give(self, s, d):
        """Fenêtre de taille acceptée par le créneau s s'il donne d et reçoit un dataset."""
        _, lb, ub, _, _ = self.slots[s]
        rest = self.sum[s] - self.inst.ds[d][1]
        return lb - rest, ub - rest

    def ok_copy(self, s, d):
        return not (self.slots[s][3] and self.inst.ds[d][2])

    def candidates(self, lo, hi):
        i, j = bisect_left(self.sizes, lo), bisect_right(self.sizes, hi)
        return self.nodes[i:j]

    def bfs(self, M, x, lo, hi, maxlen):
        """Chaîne : M reçoit w (taille dans [lo, hi]) de W, W reçoit de ..., le dernier reçoit x. Retourne la liste des
        datasets donnés [w, w2, ..., wk] (le créneau de wi reçoit w(i+1), celui de wk reçoit x) ou None."""
        inst, assign = self.inst, self.assign
        xs = inst.ds[x][1]
        visited = {M}
        parent = {}
        q = deque()
        for d in self.candidates(lo, hi):
            s = assign[d]
            if s in visited or not self.ok_copy(M, d):
                continue
            visited.add(s)
            parent[d] = None
            q.append((d, 1))
        while q:
            d, depth = q.popleft()
            s = assign[d]
            lo2, hi2 = self.window_after_give(s, d)
            if lo2 <= xs <= hi2 and self.ok_copy(s, x):
                path = [d]
                while parent[path[-1]] is not None:
                    path.append(parent[path[-1]])
                return path[::-1]
            if depth >= maxlen:
                continue
            for d2 in self.candidates(lo2, hi2):
                s2 = assign[d2]
                if s2 in visited or not self.ok_copy(s, d2):
                    continue
                visited.add(s2)
                parent[d2] = d
                q.append((d2, depth + 1))
        return None

    def apply(self, M, x, y, path):
        """Applique le mouvement : M perd x et y, reçoit path[0] ; créneau de path[i] reçoit path[i+1] ; celui de
        path[-1] reçoit x ; y libéré."""
        assign = self.assign
        chain = [assign[d] for d in path]
        self.members[M].remove(x)
        self.members[M].remove(y)
        assign[y] = -1
        incoming = path + [x]
        for i, s in enumerate(chain):
            self.members[s].remove(path[i])
        self.members[M].append(path[0])
        assign[path[0]] = M
        for i, s in enumerate(chain):
            self.members[s].append(incoming[i + 1])
            assign[incoming[i + 1]] = s
        self.rebuild()

    def check(self):
        for s, ds in self.members.items():
            _, lb, ub, fo, _ = self.slots[s]
            tot = sum(self.inst.ds[d][1] for d in ds)
            assert lb <= tot <= ub, (s, lb, tot, ub)
            assert not (fo and any(self.inst.ds[d][2] for d in ds)), s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("k", type=int)
    ap.add_argument("sol_in")
    ap.add_argument("sol_out")
    ap.add_argument("--maxlen", type=int, default=12)
    ap.add_argument("--time", type=float, default=300)
    ap.add_argument("--types", default="0,1,2,3")
    ap.add_argument("--minfree", type=int, default=1, help="taille minimale d'un dataset libéré")
    a = ap.parse_args()
    inst = Instance(a.k)
    sol = json.load(open(a.sol_in))
    slots, assign = slots_of(inst, sol)
    lp = json.load(open(os.path.join(ROOT, "runs", f"lp_{a.k}.json")))
    w = [lp["dual_total"][t] + (lp["dual_free"][t] if not c else 0) for t, _, c in inst.ds]
    t0 = time.time()

    def log(msg):
        print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)

    waste0 = sum(inst.ds[d][1] for d in range(len(inst.ds)) if assign[d] >= 0) - sum(sl[1] for sl in slots)
    log(f"m4_chain k={a.k} {len(slots)} créneaux, gaspillage {waste0}, libres {sum(1 for x in assign if x < 0)}")
    freed_total, nmoves = 0, 0
    for t in [int(x) for x in a.types.split(",")]:
        T = Type(inst, slots, assign, t)
        while time.time() - t0 < a.time:
            best = None
            multis = sorted([s for s, ds in T.members.items() if len(ds) >= 2],
                            key=lambda s: -max(inst.ds[d][1] for d in T.members[s]))
            for M in multis:
                ds = T.members[M]
                _, lb, ub, fo, _ = slots[M]
                for y in ds:
                    if inst.ds[y][1] < a.minfree:
                        continue
                    gain = w[y] * inst.ds[y][1]
                    if best is not None and gain <= best[0]:
                        continue
                    for x in ds:
                        if x == y:
                            continue
                        rest = T.sum[M] - inst.ds[x][1] - inst.ds[y][1]
                        lo, hi = lb - rest, ub - rest
                        if hi < 1:
                            continue
                        if lo <= 0 and rest >= lb:  # retrait direct de x et y (ne devrait pas arriver)
                            path = []
                        else:
                            path = T.bfs(M, x, max(lo, 1), hi, a.maxlen)
                        if path is not None:
                            best = (gain, M, x, y, path)
                            break
                if time.time() - t0 > a.time:
                    break
            if best is None:
                break
            gain, M, x, y, path = best
            if not path:
                T.members[M].remove(x); T.members[M].remove(y); assign[x] = -1; assign[y] = -1; T.rebuild()
                freed = inst.ds[x][1] + inst.ds[y][1]
            else:
                T.apply(M, x, y, path)
                freed = inst.ds[y][1]
            T.check()
            freed_total += freed
            nmoves += 1
            log(f"  type {t} : libéré dataset {y} ({inst.ds[y][1]} u., {'libre' if not inst.ds[y][2] else 'copyr.'}) via "
                f"chaîne de {len(path)} créneaux, total libéré {freed_total} ({time.time() - t0:.0f}s)")
    waste1 = sum(inst.ds[d][1] for d in range(len(inst.ds)) if assign[d] >= 0) - sum(sl[1] for sl in slots)
    dm = [[d, slots[sl][4]] for d, sl in enumerate(assign) if sl >= 0]
    new = {"dataMappings": dm, "modelMappings": sol["modelMappings"]}
    txt = json.dumps(new)
    score, ok, msg = evaluate(a.k, txt)
    ref = evaluate(a.k, open(a.sol_in).read())[0]
    with open(a.sol_out, "w") as f:
        f.write(txt if ok and score >= ref else open(a.sol_in).read())
    log(f"FIN : {nmoves} mouvements, libéré {freed_total} u., gaspillage {waste0} -> {waste1}, libres "
        f"{sum(1 for x in assign if x < 0)}, score {score} (réf {ref}) valide={ok} {msg if not ok else ''} "
        f"en {time.time() - t0:.0f}s -> {a.sol_out}")


if __name__ == "__main__":
    main()
