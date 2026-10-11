#!/bin/bash
# Boucle autonome m9 : MIP « colonnes exactes + rôles libres » répété depuis best/instance_6.json, sauvegarde via save_if_better.
# Usage : src/m9_loop.sh <worker id> "<fin UTC, ex. 2026-10-11 18:00:00 UTC>" [temps MIP s]
# Les variantes dépendent de l'id (modulo 4) ; les workers pairs ajoutent les 10 meilleures solutions du pool m6 (--extra).
W=$1; END=$(date -d "$2" +%s); T=${3:-2000}
cd "$(dirname "$0")/.."
PY=${PY:-$HOME/venv/bin/python}
[ -x "$PY" ] || PY=python
R=0
while [ $(date +%s) -lt $((END - 600)) ]; do
  R=$((R + 1)); SEED=$((W * 1000 + R)); TAG="w${W}r${R}"
  case $((W % 4)) in
    0) ARGS="--theta 5 --k1 10 --k2 10 --k3 10 --eps1 300 --eps2 5 --eps3 0";;
    1) ARGS="--theta 10 --k1 15 --k2 15 --k3 15 --eps1 500 --eps2 10 --eps3 2 --fix-gen";;
    2) ARGS="--theta 5 --k1 15 --k2 15 --k3 15 --eps1 500 --eps2 10 --eps3 2 --hcols 0.1";;
    3) ARGS="--theta 10 --k1 20 --k2 20 --k3 20 --eps1 300 --eps2 5 --eps3 1 --cross 1 --kcur 5 --fix-gen";;
  esac
  EXTRA=""
  if [ $((W % 2)) -eq 0 ] && [ -f runs/m6_pop/pop.json ]; then
    EXTRA="--extra $($PY -c "
import json;p=json.load(open('runs/m6_pop/pop.json'));m=sorted(p['members'],key=lambda x:-x['score'])[:10]
print(' '.join('runs/m6_pop/p%s.json'%x['id'] for x in m))" 2>/dev/null)"
  fi
  REMAIN=$((END - $(date +%s) - 300)); [ $REMAIN -lt $T ] && T=$REMAIN; [ $T -lt 600 ] && break
  echo "=== $(date -u +%H:%M:%S) tour $R tag $TAG seed $SEED : $ARGS $EXTRA (temps $T s)"
  timeout $((T + 900)) $PY src/m9_mip.py 6 --start best/instance_6.json $ARGS $EXTRA --time $T --threads 1 --seed $SEED --tag $TAG --save 2>&1 \
    | grep --line-buffered -E "départ|génération|modèle :|hint|MIP :|score officiel|NOUVEAU|Traceback|Error|^ +[A-Z ]*[0-9]+ +[0-9]+ +[0-9]+ +[0-9.]+% " | grep --line-buffered -vE "^ +[A-Z ]*[0-9]+ +[0-9]+ +[0-9]+ +[0-9.]+% .* [0-9]+\.[0-9]s$|  0 +0 +0 +0\.00% +-[0-9]+ +-669156 "
done
echo "=== $(date -u +%H:%M:%S) fin de la boucle worker $W"
