#!/usr/bin/env bash
# Prolongation des 3 boucles m8 (VM, cœurs 0-11) : attend la fin des boucles actuelles (fin 18:00 UTC) puis les relance
# avec les mêmes paramètres jusqu'à 19:00 UTC. Usage : setsid nohup src/relance_1800.sh > logs/relance_1800.log 2>&1 < /dev/null &
set -uo pipefail
cd "$(dirname "$0")/.."
END="2026-10-11 19:00:00 UTC"
while [ "$(pgrep -fc '^bash src/m8_loop.sh')" -gt 0 ]; do sleep 60; done
echo "$(date -u +%T) boucles m8 terminées, relance jusqu'à 19:00 UTC"
setsid nohup taskset -c 0-3  src/m8_loop.sh A2 0-3  cp    600 "$END" "3 2 1 0" 0 > logs/m8_loop_A2.log 2>&1 < /dev/null &
setsid nohup taskset -c 8-11 src/m8_loop.sh C2 8-11 cp    600 "$END" "3 2 1"   0 > logs/m8_loop_C2.log 2>&1 < /dev/null &
setsid nohup taskset -c 4-7  src/m8_loop.sh B2 4-7  highs 900 "$END" "3 2 1 0" 0 > logs/m8_loop_B2.log 2>&1 < /dev/null &
sleep 5; echo "$(date -u +%T) m8 loops: $(pgrep -fc '^bash src/m8_loop.sh')"
