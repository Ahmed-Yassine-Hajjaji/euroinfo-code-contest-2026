#!/usr/bin/env bash
# Relance run.sh <k> <n> <durée> en boucle jusqu'à une heure de fin. Usage : ./loop_lns.sh <k> <n> <durée_s> "<fin UTC>" [options lns]
set -uo pipefail
cd "$(dirname "$0")"
K=$1; N=$2; T=$3; END=$(date -d "$4" +%s); shift 4
while [ $(date +%s) -lt $((END - 120)) ]; do
  D=$T; [ $(( END - $(date +%s) )) -lt $T ] && D=$(( END - $(date +%s) ))
  ./run.sh $K $N $D "$@" > /dev/null
  sleep $((D + 30))
  while pgrep -f "venv/bin/python src/lns.py $K --lp --seed .* --time $D " > /dev/null; do sleep 10; done
done
