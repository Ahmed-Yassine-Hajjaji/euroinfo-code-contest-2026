#!/usr/bin/env bash
# Second bassin : réalisation des rôles MIP (offre effective) puis alternance rematch/LNS SANS synchronisation avec best/.
# Usage : ./basin.sh <instance> <fichier_rôles> <tag> "<fin UTC>" ; sauvegarde dans best/ seulement si meilleur (save_if_better).
set -uo pipefail
cd "$(dirname "$0")"
K=$1; ROLES=$2; TAG=$3; END=$(date -d "$4" +%s); PY=$HOME/venv/bin/python; export HIGHS_THREADS=1
CUR=runs/${TAG}_cur.json
score() { $PY -c "
import json,sys; sys.path.insert(0,'src'); from save_if_better import evaluate
print(evaluate($K, open('$1').read())[0])"; }
$PY src/lns.py $K --lp --init lp --roles $ROLES --exact 300 --time 240 --seed 31 --mu 1 --kmax 20 --save --tag $TAG > logs/${TAG}_init.log 2>&1
cp runs/lns_${K}_s31${TAG}.json $CUR
echo "$(date +%T) init : $(score $CUR)"
i=0
while [ $(date +%s) -lt $((END - 600)) ]; do
  i=$((i + 1))
  timeout 900 $PY src/rematch.py $K --start $CUR --save --time 300 --theta 40 --no-singletons --subsets --kbest 30 --out runs/${TAG}_rm.json > logs/${TAG}_rm$i.log 2>&1
  S0=$(score $CUR); S1=$(score runs/${TAG}_rm.json)
  [ "$S1" -gt "$S0" ] && cp runs/${TAG}_rm.json $CUR
  for j in 1 2 3; do
    $PY src/lns.py $K --lp --start $CUR --seed $((i * 10 + j)) --time 300 --save --save-every 60 --exact 300 --mu ${j} --kmax $((10 * j)) --tag ${TAG}_r${i}_$j > logs/${TAG}_lns_r${i}_$j.log 2>&1 &
  done
  wait
  BEST=$CUR; BS=$(score $CUR)
  for j in 1 2 3; do f=runs/lns_${K}_s$((i * 10 + j))${TAG}_r${i}_$j.json; [ -f $f ] || continue; s=$(score $f); if [ "$s" -gt "$BS" ]; then BS=$s; BEST=$f; fi; done
  [ "$BEST" != "$CUR" ] && cp $BEST $CUR
  echo "$(date +%T) tour $i : rematch $S1, LNS -> $BS"
done
