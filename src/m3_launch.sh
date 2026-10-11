#!/usr/bin/env bash
# Lance N boucles méthode 3 (tabou -> LNS/rematch) jusqu'à une heure de fin. 1 cœur par boucle.
# Usage : src/m3_launch.sh <N> "<fin UTC>" [préfixe de tag=n] [solution de départ=best/instance_6.json] [sync=1]
set -uo pipefail
cd "$(dirname "$0")/.."
N=$1; END=$2; P=${3:-n}; START=${4:-best/instance_6.json}; SYNC=${5:-1}
# variantes : tabou_s lns_s tenure lambda ncand mu kmax RM(rematch tous les RM tours, 1000 = jamais)
V=("120 300 50 1e-7 16 1 20 3" "120 300 50 1e-7 16 1 20 1000" "60 300 50 1e-7 16 1 20 3" "60 240 30 1e-7 16 2 40 1000"
   "120 300 100 1e-7 16 1 20 3" "120 300 50 3e-7 16 1 20 1000" "120 300 50 3e-8 16 1 20 3" "90 300 70 1e-7 24 1 20 3"
   "180 300 50 1e-7 16 1 20 3" "120 300 30 1e-7 16 1 40 1000" "120 180 50 1e-7 16 2 20 1000" "120 300 50 1e-7 16 1 20 2"
   "120 300 50 1e-7 16 3 20 1000" "120 300 20 1e-7 16 1 20 1000" "60 120 50 1e-7 16 1 20 1000" "120 600 50 1e-7 16 1 20 1000")
for i in $(seq 1 $N); do
  set -- ${V[$(( (i - 1) % ${#V[@]} ))]}
  setsid nohup src/m3_loop.sh 6 $P$i $((i + 200)) $1 $2 "$END" $3 $4 $5 $6 $7 $8 $START $SYNC > logs/m3_$P$i.log 2>&1 < /dev/null &
  echo "boucle $P$i : $*"
done
