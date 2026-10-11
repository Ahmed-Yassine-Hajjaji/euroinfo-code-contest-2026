#!/usr/bin/env bash
# m8 : balayage λ / mu / type de la tabou restreinte à un type depuis best/, 1 cœur. Usage :
#   src/m8_scan.sh <core> <type> "<fin UTC>" <time_s> "<lam list>" "<mu list>" [tenure=50] [ncand=16] [pert=30]
set -uo pipefail
cd "$(dirname "$0")/.."
CORE=$1; T=$2; END=$(date -d "$3" +%s); TT=$4; LAMS=$5; MUS=$6; TEN=${7:-50}; NC=${8:-16}; PERT=${9:-30}
PY=$HOME/venv/bin/python; r=0
while [ $(date +%s) -lt $((END - TT - 30)) ]; do
  for LAM in $LAMS; do for MU in $MUS; do
    r=$((r + 1)); [ $(date +%s) -lt $((END - TT - 30)) ] || break 2
    echo "$(date +%T) r$r $(taskset -c $CORE $PY src/m8_tabu.py 6 best/instance_6.json $T $((CORE * 1000 + r)) $TT --lam $LAM --mu $MU --tenure $TEN --ncand $NC --pert $PERT --tag c${CORE} --save 2>&1 | grep -E 'm8_tabu|bascule')"
  done; done
done
echo "$(date +%T) FIN"
