#!/usr/bin/env bash
# Lance N boucles méthode 2 (src/m2_loop.sh) en parallèle depuis best/ (ou un fichier), blocs/graines variés.
# Chaque boucle = 4 procs (empaquetage) puis 5 procs (4 LNS + 1 rematch) : ~5 cœurs par boucle en moyenne.
# Usage : src/m2_night.sh <k> <N boucles> "<fin UTC>" [start.json=best/instance_k.json] [tag=N]
set -uo pipefail
cd "$(dirname "$0")/.."
K=$1; N=$2; END=$3; START=${4:-best/instance_$K.json}; TAG=${5:-N}
BLOCKS=(120 100 140 120 100); KCOLS=(200 200 150 300 150); DELTAS=(20 30 20 10 40)
for i in $(seq 1 $N); do
  j=$(( (i - 1) % ${#BLOCKS[@]} ))
  setsid nohup src/m2_loop.sh $K "$START" ${TAG}$i "$END" $((10 + i)) ${BLOCKS[$j]} ${KCOLS[$j]} ${DELTAS[$j]} 240 \
    > logs/m2_loop_${TAG}$i.log 2>&1 < /dev/null &
  echo "boucle ${TAG}$i : bloc ${BLOCKS[$j]} kcol ${KCOLS[$j]} delta ${DELTAS[$j]} -> logs/m2_loop_${TAG}$i.log"
done
