#!/usr/bin/env python3
"""m6 : un worker mémétique (1 cœur). Boucle jusqu'à --until :
  parents A (tournoi) et B (membre éloigné) dans runs/m6_pop/ -> m6_cross (chaînes d'éjection, rôles de A)
  -> tabou m3 (--tabu s) -> LNS (--lns s) -> rematch (--rm s, si proche du meilleur) -> save_if_better --method "m6 ..."
  -> remplacement : remplace le plus faible si meilleur et distance >= dmin à tous, sinon le plus proche s'il est meilleur.
Usage : python src/m6_worker.py <k> <tag> <seed> --until <epoch> [--tabu 120] [--lns 240] [--rm 240] [--rm-gap 150]
        [--mix 0.3,0.6,1.0] [--dmin 300] [--tenure 50] [--lam 1e-7] [--ncand 16]
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m6_common import ROOT, Instance, pack_set, distance, waste_of, Lock, load_pop, save_pop, member_path  # noqa: E402
from save_if_better import evaluate, save_if_better  # noqa: E402

PY = sys.executable
BIN = os.path.join(ROOT, "src", "m3_tabu", "target", "release", "m3_tabu")


def now():
    return time.strftime("%H:%M:%S")


def run(cmd, log, timeout):
    with open(log, "w") as f:
        try:
            return subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout, cwd=ROOT).returncode
        except subprocess.TimeoutExpired:
            return -9


def score(k, inst, path):
    try:
        with open(path) as f:
            txt = f.read()
        sc, ok, _ = evaluate(k, txt, inst.txt)
        return sc if ok else 0
    except Exception:
        return 0


def best_score(k):
    try:
        with open(os.path.join(ROOT, "best", "scores.json")) as f:
            return json.load(f)[str(k)]["score"]
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int); ap.add_argument("tag"); ap.add_argument("seed", type=int)
    ap.add_argument("--until", type=float, required=True)
    ap.add_argument("--tabu", type=float, default=120); ap.add_argument("--lns", type=float, default=240)
    ap.add_argument("--rm", type=float, default=240); ap.add_argument("--rm-gap", type=int, default=150)
    ap.add_argument("--rm-waste", type=int, default=50, help="rematch seulement si gaspillage <= min population + rm-waste")
    ap.add_argument("--mix", default="0.3,0.6,1.0"); ap.add_argument("--maxchain", type=int, default=4)
    ap.add_argument("--dmin", type=int, default=300)
    ap.add_argument("--tenure", type=int, default=50); ap.add_argument("--lam", default="1e-7"); ap.add_argument("--ncand", type=int, default=16)
    ap.add_argument("--mu", default="1"); ap.add_argument("--kmax", type=int, default=20)
    ap.add_argument("--pbest", type=float, default=0.3, help="probabilité de prendre le meilleur membre comme parent A")
    a = ap.parse_args()
    k, tag = a.instance, a.tag
    inst = Instance(k)
    rng = random.Random(a.seed)
    mixes = [float(x) for x in a.mix.split(",")]
    os.environ["HIGHS_THREADS"] = "1"
    R = lambda n: os.path.join(ROOT, "runs", f"m6_{tag}_{n}")  # noqa: E731
    L = lambda n: os.path.join(ROOT, "logs", f"m6_{tag}_{n}.log")  # noqa: E731
    cache = {}

    def packs_cached(path):
        mt = os.path.getmtime(path)
        if path not in cache or cache[path][0] != mt:
            with open(path) as f:
                cache[path] = (mt, pack_set(inst, json.load(f)))
        return cache[path][1]

    r = 0
    print(f"{now()} worker {tag} seed {a.seed} : tabou {a.tabu}s lns {a.lns}s rm {a.rm}s mix {mixes} dmin {a.dmin}", flush=True)
    while time.time() < a.until - a.tabu - a.lns - 90:
        r += 1
        seed = a.seed * 1000 + r
        # ---- choix des parents ----
        key = lambda m: (m["score"], -m.get("waste", 10**9))  # noqa: E731
        with Lock():
            pop = load_pop()
            ms = sorted(pop["members"], key=key, reverse=True)
            if len(ms) < 2:
                print(f"{now()} population trop petite, attente"); time.sleep(60); continue
            if rng.random() < a.pbest:
                A = ms[0]
            else:
                c1, c2 = rng.sample(ms, 2)
                A = c1 if key(c1) >= key(c2) else c2
            others = [m for m in ms if m["id"] != A["id"]]
            pA = packs_cached(A["file"])
            dists = [(distance(pA, packs_cached(m["file"])), m) for m in others]
            far = [m for d, m in dists if d >= a.dmin] or [m for d, m in dists]
            B = rng.choice(far)
            dAB = next(d for d, m in dists if m["id"] == B["id"])
            shutil.copy(A["file"], R("A.json")); shutil.copy(B["file"], R("B.json"))
        p = rng.choice(mixes)
        # ---- croisement ----
        child = R("child.json")
        rc = run([PY, os.path.join(ROOT, "src", "m6_cross.py"), str(k), R("A.json"), R("B.json"), child, "--mix", str(p), "--seed", str(seed),
                  "--maxchain", str(a.maxchain)], L("cross"), 300)
        info = ""
        try:
            info = [l for l in open(L("cross")).read().splitlines() if l.startswith("m6_cross")][-1]
        except Exception:
            pass
        s0 = score(k, inst, child) if rc == 0 else 0
        if s0 == 0:
            print(f"{now()} tour {r} : croisement p{A['id']} x p{B['id']} (p={p}) invalide rc={rc} {info[:200]}", flush=True)
            continue
        dA0 = distance(pack_set(inst, json.load(open(child))), pA)
        w0 = waste_of(inst, json.load(open(child)))
        # ---- tabou ----
        cur = child
        run([PY, os.path.join(ROOT, "src", "m3_prep.py"), "prep", str(k), cur, R("tab.in")], L("prep"), 120)
        run([BIN, R("tab.in"), R("tab.out"), str(seed), str(int(a.tabu)), str(a.tenure), a.lam, str(a.ncand), "2000000", "30"], L("tabu"), a.tabu + 60)
        tb = ""
        try:
            tb = [l for l in open(L("tabu")).read().splitlines() if "gaspillage" in l][-1].split("gaspillage")[1].strip()[:40]
        except Exception:
            pass
        rc = run([PY, os.path.join(ROOT, "src", "m3_prep.py"), "rebuild", str(k), cur, R("tab.out"), R("tab.json")], L("rebuild"), 120)
        s1 = score(k, inst, R("tab.json")) if rc == 0 else 0
        if s1 >= s0:
            cur = R("tab.json")
        else:
            s1 = s0
        w1 = waste_of(inst, json.load(open(cur)))
        # ---- LNS ----
        lns_out = os.path.join(ROOT, "runs", f"lns_{k}_s{seed}_m6{tag}.json")
        run([PY, os.path.join(ROOT, "src", "lns.py"), str(k), "--lp", "--start", cur, "--seed", str(seed), "--mu", a.mu, "--kmax", str(a.kmax),
             "--exact", "300", "--time", str(a.lns), "--save-every", "60", "--tag", f"_m6{tag}"], L("lns"), a.lns + 120)
        s2 = score(k, inst, lns_out)
        if s2 >= s1:
            cur = lns_out
        else:
            s2 = s1
        # ---- rematch si proche du meilleur ----
        s3 = s2; what = ""
        bs = best_score(k)
        sol2 = json.load(open(cur))
        w2 = waste_of(inst, sol2)
        minw = min([m.get("waste", 10**9) for m in ms] + [10**9])
        used2 = {d for d, _ in sol2["dataMappings"]}
        free2 = [d for d in range(len(inst.ds)) if d not in used2]
        if a.rm > 0 and s2 >= bs - a.rm_gap and (s2 > bs or len(free2) >= 2 or w2 <= minw + a.rm_waste) and time.time() < a.until - a.rm - 60:
            # datasets libres -> paquets « singletons » (via un pseudo-fichier --extra-sols) : le MIP peut s'en servir (h -> f, échanges)
            dmf = []
            for d in free2:
                t = inst.ds[d][0]
                mm_ = next(m for m in range(len(inst.value)) if any(tt == t for tt, _, _ in inst.reqs[m]) and m not in [x[1] for x in dmf])
                dmf.append([d, mm_])
            with open(R("free.json"), "w") as f:
                json.dump({"dataMappings": dmf, "modelMappings": []}, f)
            run([PY, os.path.join(ROOT, "src", "rematch.py"), str(k), "--start", cur, "--time", str(a.rm), "--theta", "40", "--no-singletons",
                 "--subsets", "--kbest", "30", "--extra-sols", R("free.json"), "--out", R("rm.json")], L("rm"), a.rm + 600)
            s3 = score(k, inst, R("rm.json"))
            if s3 >= s2:
                cur = R("rm.json"); what = f" rm {s3}"
            else:
                s3 = s2
        # ---- sauvegarde officielle ----
        final = R(f"c{r}.json")
        shutil.copy(cur, final)
        with open(final) as f:
            txt = f.read()
        code, _ = save_if_better(k, txt, method=f"m6 {tag} r{r} p{A['id']}x p{B['id']} mix={p}", dataset_txt=inst.txt)
        # ---- population ----
        pC = pack_set(inst, json.load(open(final)))
        wC = waste_of(inst, json.load(open(final)))
        with Lock():
            pop = load_pop()
            st = pop["stats"]
            st["children"] += 1
            beat = s3 > max(A["score"], B["score"])
            st["beat_parent"] += int(beat)
            st["lower_waste"] = st.get("lower_waste", 0) + int(s3 >= max(A["score"], B["score"]) and wC < min(A.get("waste", 10**9), B.get("waste", 10**9)))
            st["min_waste"] = min(st.get("min_waste", 10**9), wC)
            st["best_child"] = max(st["best_child"], s3)
            ms = pop["members"]
            dl = sorted(((distance(pC, packs_cached(m["file"])), m) for m in ms), key=lambda x: x[0])
            weakest = min(ms, key=key)
            action = "rejeté"
            target = None
            kC = (s3, -wC)
            if dl and dl[0][0] >= a.dmin and kC > key(weakest):
                target, action = weakest, f"remplace le plus faible p{weakest['id']} ({weakest['score']})"
            elif dl and dl[0][0] < a.dmin and kC > key(dl[0][1]):
                target, action = dl[0][1], f"remplace le plus proche p{dl[0][1]['id']} ({dl[0][1]['score']}, d={dl[0][0]})"
            if target is not None:
                mid = pop["next_id"]; pop["next_id"] += 1
                shutil.copy(final, member_path(mid))
                ms.remove(target)
                ms.append({"id": mid, "file": member_path(mid), "score": s3, "origin": f"{tag} r{r} p{A['id']}xp{B['id']} mix={p}", "gen": max(A["gen"], B["gen"]) + 1, "waste": wC})
                st["inserted"] += 1
            save_pop(pop)
        print(f"{now()} tour {r} : p{A['id']}({A['score']}) x p{B['id']}({B['score']}) dAB={dAB} mix={p} -> enfant {s0} dA={dA0} gasp {w0} ; "
              f"tabou [{tb}] -> {s1} gasp {w1} ; lns -> {s2} libres {len(free2)}{what} ; final {s3} gasp {wC} dmin={dl[0][0] if dl else '-'} ; {action}{' GASP<parents' if wC < min(A.get('waste', 10**9), B.get('waste', 10**9)) else ''} ; "
              f"{'SAUVÉ' if code == 0 else ''} best/ {best_score(k)}", flush=True)
    print(f"{now()} FIN worker {tag} après {r} tours", flush=True)


if __name__ == "__main__":
    main()
