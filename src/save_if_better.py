#!/usr/bin/env python3
"""Valide une solution avec le scoreur officiel et la copie dans best/ si strictement meilleure.

Usage : python src/save_if_better.py <instance 1-7> <solution.json> [--method "texte"] [--no-commit]

- Validation : getSolutionScore de test_solution.py (référence absolue), plus un contrôle strict
  des indices (le scoreur officiel accepte des indices négatifs dans modelMappings : on les refuse).
- Verrou de fichier (fcntl) : plusieurs processus peuvent appeler ce script en parallèle.
- best/instance_<k>.json + best/scores.json, puis commit git avec le score dans le message.
Code de retour : 0 = sauvegardé, 1 = valide mais pas meilleur, 2 = invalide.
"""
import argparse
import fcntl
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from test_solution import getSolutionScore  # noqa: E402

BEST = os.path.join(ROOT, "best")
SCORES = os.path.join(BEST, "scores.json")


def dataset_path(k):
    return os.path.join(ROOT, "datasets", f"instance_{k}.json")


def strict_check(sol, ds):
    """Contrôles que le scoreur officiel ne fait pas (indices négatifs / hors bornes)."""
    nm, nd = len(ds["models"]), len(ds["datasets"])
    for d, m in sol.get("dataMappings", []):
        if not (0 <= d < nd and 0 <= m < nm):
            return f"indice hors bornes dans dataMappings: {[d, m]}"
    for s, t in sol.get("modelMappings", []):
        if not (0 <= s < nm and 0 <= t < nm):
            return f"indice hors bornes dans modelMappings: {[s, t]}"
    return None


def evaluate(k, solution_txt, dataset_txt=None):
    """Retourne (score, valide, message) selon le scoreur officiel + contrôle strict."""
    if dataset_txt is None:
        with open(dataset_path(k)) as f:
            dataset_txt = f.read()
    try:
        score, ok, msg = getSolutionScore(solution_txt, dataset_txt, show_details=False)
    except Exception as e:  # le scoreur peut lever (ex. IndexError) sur une solution malformée
        return 0, False, f"exception du scoreur: {e!r}"
    if ok:
        err = strict_check(json.loads(solution_txt), json.loads(dataset_txt))
        if err:
            return 0, False, err
    return score, ok, msg


def save_if_better(k, solution_txt, method="", commit=True, dataset_txt=None):
    score, ok, msg = evaluate(k, solution_txt, dataset_txt)
    if not ok:
        print(f"[instance {k}] INVALIDE : {msg}")
        return 2, score
    os.makedirs(BEST, exist_ok=True)
    with open(os.path.join(BEST, ".lock"), "w") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        scores = {}
        if os.path.exists(SCORES):
            with open(SCORES) as f:
                scores = json.load(f)
        prev = scores.get(str(k), {}).get("score", 0)
        if score <= prev:
            print(f"[instance {k}] valide, score {score} <= meilleur {prev} : non sauvegardé")
            return 1, score
        dst = os.path.join(BEST, f"instance_{k}.json")
        tmp = dst + f".tmp{os.getpid()}"
        with open(tmp, "w") as f:
            f.write(solution_txt)
        os.replace(tmp, dst)
        scores[str(k)] = {"score": score, "method": method,
                          "date": time.strftime("%Y-%m-%d %H:%M:%S")}
        with open(SCORES + ".tmp", "w") as f:
            json.dump(scores, f, indent=2, sort_keys=True)
        os.replace(SCORES + ".tmp", SCORES)
        print(f"[instance {k}] NOUVEAU MEILLEUR : {prev} -> {score} ({method})")
        if commit:
            subprocess.run(["git", "add", dst, SCORES], cwd=ROOT, check=False)
            subprocess.run(["git", "commit", "-q", "-m",
                            f"best instance {k}: {score} (avant {prev}) [{method}]\n\n"
                            "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>",
                            "--", dst, SCORES], cwd=ROOT, check=False)
    return 0, score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", type=int)
    ap.add_argument("solution")
    ap.add_argument("--method", default="")
    ap.add_argument("--no-commit", action="store_true")
    a = ap.parse_args()
    with open(a.solution) as f:
        txt = f.read()
    code, _ = save_if_better(a.instance, txt, a.method, commit=not a.no_commit)
    sys.exit(code)


if __name__ == "__main__":
    main()
