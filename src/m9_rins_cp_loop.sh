#!/bin/bash
# Boucle RINS m9 : un sous-problème (modèle + seuils) résolu par CP-SAT (sous-processus) ou HiGHS, relancé jusqu'à la fin.
# Usage : src/m9_rins_cp_loop.sh <id> "<fin UTC>" <cp|highs> <nb workers CP-SAT | threads HiGHS> <variante modèle 0-2> <seuils> [cutoff] [tranche s]
ID=$1; FIN=$2; END=$(date -d "$FIN" +%s); MODE=$3; NW=$4; V=$5; THR=$6; CUT=${7:-1}; SL=${8:-900}
cd "$(dirname "$0")/.."
PY=${PY:-$HOME/venv/bin/python}; [ -x "$PY" ] || PY=python
case $V in
  0) GEN="--theta 5 --k1 10 --k2 10 --k3 10 --eps1 300 --eps2 5 --eps3 0";;                   # 173 k col., LP 669 688
  1) GEN="--theta 10 --k1 15 --k2 15 --k3 15 --eps1 500 --eps2 10 --eps3 2 --fix-gen";;       # 157 k col., LP 669 584
  2) GEN="--theta 5 --k1 8 --k2 8 --k3 8 --eps1 300 --eps2 5 --eps3 1 --fix-gen --hcols 0.1";; # 93 k col., LP 669 577
esac
RINS="--thresholds $THR --frac 1.0 --eps0 1e-6 --fix-roles 1 --cutoff $CUT --slice $SL"
R=0
while [ $(date +%s) -lt $((END - 600)) ]; do
  R=$((R + 1)); TAG="${MODE}${ID}r${R}"
  echo "=== $(date -u +%H:%M:%S) tour $R tag $TAG : $GEN | $RINS ($MODE $NW)"
  if [ "$MODE" = cp ]; then
    timeout $((END - $(date +%s) + 300)) $PY src/m9_rins_cp.py 6 --start best/instance_6.json $GEN $RINS --cp-workers $NW --lp-threads 1 \
      --until "$FIN" --seed $ID --tag $TAG --save 2>&1 | grep --line-buffered -vE "^\s*$"
  else
    T=$((END - $(date +%s) - 120))
    timeout $((T + 600)) $PY src/m9_rins.py 6 --start best/instance_6.json $GEN $RINS --total $T --threads $NW --lp-threads 1 \
      --seed $ID --tag $TAG --save 2>&1 | grep --line-buffered -vE "^\s*$"
  fi
done
echo "=== $(date -u +%H:%M:%S) fin de la boucle $MODE $ID"
