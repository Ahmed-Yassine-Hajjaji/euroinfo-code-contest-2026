#!/bin/bash
# Boucle autonome m9 RINS (plongeon guidé par le LP) : src/m9_rins.py répété depuis best/instance_6.json, sauvegarde via save_if_better.
# Usage : src/m9_rins_loop.sh <worker id> "<fin UTC, ex. 2026-10-11 18:00:00 UTC>" [temps total par processus s] [threads]
# Variantes selon l'id : modèle (w mod 3), paramètres RINS (w mod 4). Le modèle d'un worker est fixe (graine = w) :
# sa LP racine est mise en cache (runs/m9_rins_lp_<hash>.npz) et réutilisée tant que best/ ne change pas.
W=$1; END=$(date -d "$2" +%s); T=${3:-2400}; TH=${4:-1}
cd "$(dirname "$0")/.."
PY=${PY:-$HOME/venv/bin/python}
[ -x "$PY" ] || PY=python
R=0
while [ $(date +%s) -lt $((END - 480)) ]; do
  R=$((R + 1)); TAG="w${W}r${R}"
  case $((W % 3)) in
    0) GEN="--theta 5 --k1 10 --k2 10 --k3 10 --eps1 300 --eps2 5 --eps3 0";;                 # 173 k col., LP 669 688
    1) GEN="--theta 10 --k1 15 --k2 15 --k3 15 --eps1 500 --eps2 10 --eps3 2 --fix-gen";;     # 157 k col., LP 669 583
    2) GEN="--theta 5 --k1 8 --k2 8 --k3 8 --eps1 300 --eps2 5 --eps3 1 --fix-gen --hcols 0.1";; # ~110 k col., rapide
  esac
  case $((W % 4)) in
    0) RINS="--thresholds 0.9,0.7 --frac 1.0,0.9 --eps0 1e-6,1e-3 --cutoff 1 --fix-roles 1 --slice 300";;
    1) RINS="--thresholds 0.9,0.5 --frac 1.0,0.85 --eps0 1e-6 --cutoff 0 --fix-roles 1 --slice 600";;
    2) RINS="--thresholds 0.5,0.3 --frac 1.0 --eps0 1e-3,1e-6 --cutoff 1 --fix-roles 1 --slice 600";;   # petit voisinage, preuve rapide
    3) RINS="--thresholds 0.7 --frac 1.0,0.9 --eps0 1e-6 --cutoff 0 --fix-roles 1 --slice 1500";;      # tranche longue avec incumbent
  esac
  REMAIN=$((END - $(date +%s) - 240)); [ $REMAIN -lt $T ] && T=$REMAIN; [ $T -lt 480 ] && break
  echo "=== $(date -u +%H:%M:%S) tour $R tag $TAG : $GEN | $RINS (total $T s, threads $TH)"
  timeout $((T + 600)) $PY src/m9_rins.py 6 --start best/instance_6.json $GEN $RINS --total $T --threads $TH --lp-threads $TH \
    --seed $W --tag $TAG --save 2>&1 | grep --line-buffered -vE "^\s*$"
done
echo "=== $(date -u +%H:%M:%S) fin de la boucle worker $W"
