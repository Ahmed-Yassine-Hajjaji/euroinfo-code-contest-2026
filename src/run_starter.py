"""Lance starter.py (solve) sur une instance et écrit runs/starter_<k>.json + le score officiel."""
import os, sys, json, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from starter import solve
from test_solution import getSolutionScore

k = int(sys.argv[1])
txt = open(os.path.join(ROOT, "datasets", f"instance_{k}.json")).read()
t = time.time()
sol = json.dumps(solve(txt))
os.makedirs(os.path.join(ROOT, "runs"), exist_ok=True)
open(os.path.join(ROOT, "runs", f"starter_{k}.json"), "w").write(sol)
print(f"\nSTARTER instance {k}: {getSolutionScore(sol, txt, False)} en {time.time()-t:.0f}s")
