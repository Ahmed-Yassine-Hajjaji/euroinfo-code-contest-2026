#!/usr/bin/env bash
# Alternance rematch (MIP paquets <-> modèles, départ best/) et LNS multi-graines (--sync), N tours.
# Usage : ./iterate.sh <instance> <tours> <durée_rematch_s> <durée_lns_s> <nb_lns> <cœurs ex. 4-9> [options rematch]
# Chaque étape passe par save_if_better (jamais d'écriture directe dans best/). Logs : logs/iter_<k>_r<i>_*.log
set -uo pipefail
cd "$(dirname "$0")"
K=$1; N=$2; TR=$3; TL=$4; NL=$5; CORES=$6; shift 6
PY=${PY:-$HOME/venv/bin/python}
export HIGHS_THREADS=1
mapfile -t CL < <(seq ${CORES%-*} ${CORES#*-})
for i in $(seq 1 $N); do
  echo "$(date +%T) tour $i : rematch ($TR s)"
  timeout $((TR + 600)) taskset -c ${CL[0]} $PY src/rematch.py $K --save --time $TR "$@" --out runs/iter_${K}_r$i.json \
    > logs/iter_${K}_r${i}_rematch.log 2>&1
  grep -E 'score officiel|NOUVEAU|Error' logs/iter_${K}_r${i}_rematch.log | tail -2
  echo "$(date +%T) tour $i : LNS $NL x $TL s"
  BASE=$(( $(date +%s) % 100000 ))
  MUS=(1 2 1 0.5 1 3); KM=(20 40 10 20 15 30)
  for j in $(seq 1 $NL); do
    S=$((BASE + j)); c=${CL[$(( (j - 1) % ${#CL[@]} ))]}
    nohup timeout $((TL + 300)) taskset -c $c $PY src/lns.py $K --lp --seed $S --time $TL --save --sync --save-every 60 \
      --exact 300 --mu ${MUS[$((j % 6))]} --kmax ${KM[$((j % 6))]} > logs/iter_${K}_r${i}_lns_s$S.log 2>&1 &
  done
  wait
  grep -h NOUVEAU logs/iter_${K}_r${i}_lns_*.log | tail -2
done
