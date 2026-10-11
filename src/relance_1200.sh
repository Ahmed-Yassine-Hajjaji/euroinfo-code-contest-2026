#!/usr/bin/env bash
# Relance automatique sur AWS : à 12:00 UTC, quand les 8 workers m6 et les 4 boucles rematch se sont arrêtés,
# relance 8 boucles m3 (graines nouvelles 401-408, sync best/) + 4 boucles rematch jusqu'à 18:00 UTC.
# Usage : setsid nohup src/relance_1200.sh > logs/relance_1200.log 2>&1 < /dev/null &
set -uo pipefail
cd "$(dirname "$0")/.."
T0=$(date -d "2026-10-11 12:00:30 UTC" +%s); END="2026-10-11 18:00:00 UTC"
while [ $(date +%s) -lt $T0 ]; do sleep 30; done
echo "$(date -u +%T) 12:00 atteint, attente de la fin des workers m6 / rematch"
for i in $(seq 1 40); do
  n=$(( $(pgrep -fc "venv/bin/python src/m6_worker.py") + $(pgrep -fc "^bash ./loop_rematch.sh") ))
  [ "$n" -eq 0 ] && break; sleep 30
done
echo "$(date -u +%T) restants m6/rematch : $n ; lancement"
V=("120 300 50 1e-7 16 1 20 3" "120 300 50 1e-7 16 1 20 1000" "60 300 50 1e-7 16 1 20 3" "60 240 30 1e-7 16 2 40 1000"
   "120 300 100 1e-7 16 1 20 3" "120 300 50 3e-7 16 1 20 1000" "90 300 70 1e-7 24 1 20 3" "180 300 50 1e-7 16 1 20 3")
for i in $(seq 1 8); do
  set -- ${V[$((i - 1))]}
  setsid nohup src/m3_loop.sh 6 r$i $((400 + i)) $1 $2 "$END" $3 $4 $5 $6 $7 $8 best/instance_6.json 1 > logs/m3_r$i.log 2>&1 < /dev/null &
  echo "boucle r$i graine $((400 + i)) : $*"
done
for c in 0 1 2 3; do
  setsid nohup ./loop_rematch.sh 6 $c 600 "$END" $((c + 4)) > logs/loopR_6_c${c}_pm.log 2>&1 < /dev/null &
  echo "rematch c$c"
done
sleep 10
echo "$(date -u +%T) m3 loops: $(pgrep -fc '^bash src/m3_loop.sh')  rematch: $(pgrep -fc '^bash ./loop_rematch.sh')  $(uptime)"
