#!/usr/bin/env bash
# m6 : lance N workers mémétiques (1 cœur chacun) jusqu'à une heure de fin. Population dans runs/m6_pop/ (m6_pool.py init).
# Usage : src/m6_launch.sh <N> "<fin UTC>" [préfixe=w] [tabou_s=120] [lns_s=240] [rm_s=240] [mix=0.3,0.6,1.0] [dmin=300]
set -uo pipefail
cd "$(dirname "$0")/.."
N=$1; END=$(date -d "$2" +%s); P=${3:-w}; TT=${4:-120}; TL=${5:-240}; RM=${6:-240}; MIX=${7:-0.3,0.6,1.0}; DMIN=${8:-300}
PY=$HOME/venv/bin/python
for i in $(seq 1 $N); do
  setsid nohup $PY src/m6_worker.py 6 $P$i $((i + 600)) --until $END --tabu $TT --lns $TL --rm $RM --mix $MIX --dmin $DMIN \
    > logs/m6_$P$i.log 2>&1 < /dev/null &
  echo "worker $P$i lancé (fin $(date -u -d @$END +%H:%M:%S) UTC)"
done
