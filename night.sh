#!/usr/bin/env bash
# Runs de nuit : 12 processus détachés (setsid nohup) jusqu'à une heure de fin absolue.
# Usage : ./night.sh "2026-10-10 07:00:00 UTC"
set -euo pipefail
cd "$(dirname "$0")"
PY=${PY:-$HOME/venv/bin/python}
END=$(date -d "$1" +%s)
mkdir -p logs runs
C="--lp --save --save-every 120 --exact 300 --until $END"

launch() {  # launch <nom> <commande...>
  local name=$1; shift
  setsid nohup bash -c "$*" > logs/night_$name.log 2>&1 < /dev/null &
  echo "lancé $name"
}
# Instance 6 : 5 processus (2 sync, 3 indépendants dont 2 en recuit)
launch 6a "$PY src/lns.py 6 $C --seed 6001 --sync --mu 1 --kmax 20"
launch 6b "$PY src/lns.py 6 $C --seed 6002 --sync --mu 2 --kmax 40"
launch 6c "$PY src/lns.py 6 $C --seed 6003 --mu 1 --kmax 20 --temp 5 --tag c"
launch 6d "$PY src/lns.py 6 $C --seed 6004 --mu 0.5 --kmax 10 --temp 10 --tag d"
launch 6e "$PY src/lns.py 6 $C --seed 6005 --mu 3 --kmax 30 --tag e"
# Instance 2 : 2 processus
launch 2a "$PY src/lns.py 2 $C --seed 2001 --sync --mu 1 --kmax 20"
launch 2b "$PY src/lns.py 2 $C --seed 2002 --sync --mu 2 --kmax 10"
# Instance 5 : 2 processus
launch 5a "$PY src/lns.py 5 $C --seed 5001 --sync --mu 1 --kmax 20 --exact 5000"
launch 5b "$PY src/lns.py 5 $C --seed 5002 --sync --mu 2 --kmax 40 --exact 5000"
# Instance 7 : 1 processus
launch 7a "$PY src/lns.py 7 $C --seed 7001 --sync --mu 1 --kmax 20"
# Instance 4 : MIP des rôles (4 h), réalisation exacte, puis LNS jusqu'à la fin
launch 4a "timeout 15000 taskset -c 13 $PY src/lp_bound.py --mip 14400 4 2>/dev/null | grep '^inst'; \
  $PY src/lns.py 4 --lp --init lp --roles runs/mip_4.json --exact 100000 --save --save-every 120 --until $END \
  --seed 4001 --mu 1 --kmax 20 --tag mipnuit"
# Instance 3 : jusqu'à 523 758, puis le cœur passe à l'instance 6
if [ "$($PY -c "import json;print(json.load(open('best/scores.json'))['3']['score'])")" -lt 523758 ]; then
  launch 3a "$PY src/lns.py 3 $C --seed 3002 --sync --mu 1 --kmax 20 --target 523758; \
    $PY src/lns.py 6 $C --seed 6006 --sync --mu 1.5 --kmax 15 --tag f"
else
  launch 6f "$PY src/lns.py 6 $C --seed 6006 --sync --mu 1.5 --kmax 15 --tag f"
fi
