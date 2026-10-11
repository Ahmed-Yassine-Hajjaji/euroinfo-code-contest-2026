#!/usr/bin/env bash
# Usage : ./run.sh <instance> <nb_graines> <durée_s> [options lns.py supplémentaires]
# Lance nb_graines LNS en parallèle (nohup), départ best/, prix LP, sauvegarde via save_if_better, logs dans logs/.
# Diversité par graine : mu (poids du gaspillage) et kmax (taille de destruction).
set -euo pipefail
cd "$(dirname "$0")"
K=$1; N=$2; T=$3; shift 3
PY=${PY:-$HOME/venv/bin/python}
mkdir -p logs runs
[ -f runs/lp_$K.json ] || $PY src/lp_bound.py $K
MUS=(1 0.5 2 1 3 1); KMAXS=(20 10 40 20)
BASE=$(( $(date +%s) % 100000 ))
for i in $(seq 1 $N); do
  S=$((BASE + i))
  MU=${MUS[$((i % ${#MUS[@]}))]}; KMAX=${KMAXS[$((i % ${#KMAXS[@]}))]}
  nohup timeout $((T + 300)) $PY src/lns.py $K --lp --seed $S --time $T --save --sync --save-every 60 \
    --mu $MU --kmax $KMAX --exact 300 "$@" > logs/lns_${K}_s${S}.log 2>&1 &
  echo "instance $K graine $S mu=$MU kmax=$KMAX -> logs/lns_${K}_s${S}.log"
done
