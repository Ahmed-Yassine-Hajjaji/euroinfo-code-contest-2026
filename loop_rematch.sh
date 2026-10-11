#!/usr/bin/env bash
# Boucle rematch : relance src/rematch.py depuis best/ avec des variantes alternées jusqu'à une heure de fin.
# Usage : ./loop_rematch.sh <instance> <cœur> <durée_s par run> "<fin, ex. 2026-10-10 11:50:00 UTC>"
set -uo pipefail
cd "$(dirname "$0")"
K=$1; CORE=$2; T=$3; END=$(date -d "$4" +%s); export HIGHS_THREADS=1
V=("--theta 40 --no-singletons --subsets --kbest 30" "--theta 60 --no-singletons --subsets --kbest 40"
   "--theta 30 --subsets --kbest 20" "--theta 80 --no-singletons --subsets --kbest 25")
i=${5:-0}
while [ $(date +%s) -lt $((END - T)) ]; do
  opt=${V[$((i % ${#V[@]}))]}; i=$((i + 1))
  log=logs/loopR_${K}_c${CORE}_$i.log
  timeout $((T + 900)) taskset -c $CORE $HOME/venv/bin/python src/rematch.py $K --save --time $T $opt --out runs/loopR_${K}_c${CORE}.json > $log 2>&1
  echo "$(date +%T) run $i [$opt] : $(grep -hE 'score officiel|NOUVEAU|dumped|Error' $log | tail -1 | cut -c1-100)"
done
