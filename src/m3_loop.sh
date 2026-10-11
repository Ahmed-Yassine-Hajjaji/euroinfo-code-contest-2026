#!/usr/bin/env bash
# Méthode 3 : boucle tabou (rôles fixés, réduction du gaspillage) -> LNS (conversion des datasets libérés en score)
# [-> rematch tous les RM tours]. 1 cœur. Usage :
#   src/m3_loop.sh <k> <tag> <seed> <tabou_s> <lns_s> "<fin UTC>" [tenure=50] [lambda=1e-7] [ncand=16] [mu=1] [kmax=20] [RM=3] [start] [sync=0]
# sync=1 : à chaque tour, repart de best/instance_k.json s'il est strictement meilleur que le courant.
set -uo pipefail
cd "$(dirname "$0")/.."
K=$1; TAG=$2; SEED=$3; TT=$4; TL=$5; END=$(date -d "$6" +%s); TEN=${7:-50}; LAM=${8:-1e-7}; NC=${9:-16}
MU=${10:-1}; KMAX=${11:-20}; RM=${12:-3}; START=${13:-runs/start_m23_6.json}; SYNC=${14:-0}
PY=$HOME/venv/bin/python; BIN=src/m3_tabu/target/release/m3_tabu; export HIGHS_THREADS=1
score() { $PY -c "
import sys; sys.path.insert(0,'src'); from save_if_better import evaluate
print(evaluate($K, open('$1').read())[0])"; }
waste() { $PY src/waste_split.py $K $1; }
CUR=runs/m3_${TAG}_cur.json; cp $START $CUR
S=$(score $CUR); r=0
echo "$(date +%T) départ $S gaspillage $(waste $CUR) (tenure $TEN lambda $LAM ncand $NC mu $MU kmax $KMAX)"
while [ $(date +%s) -lt $((END - TT - TL - 60)) ]; do
  r=$((r + 1))
  if [ "$SYNC" = 1 ]; then BS=$(grep -A3 "\"$K\"" best/scores.json | grep -oE "\"score\": [0-9]+" | grep -oE "[0-9]+"); if [ "$BS" -gt "$S" ]; then cp best/instance_$K.json $CUR; S=$BS; echo "$(date +%T) sync best/ $BS"; fi; fi
  $PY src/m3_prep.py prep $K $CUR runs/m3_${TAG}.in > /dev/null
  timeout $((TT + 60)) $BIN runs/m3_${TAG}.in runs/m3_${TAG}.out $((SEED * 1000 + r)) $TT $TEN $LAM $NC 2000000 30 > logs/m3_${TAG}_tabu.log 2>&1
  TB=$(grep -oE "gaspillage [0-9]+ -> [0-9]+" logs/m3_${TAG}_tabu.log | tail -1)
  $PY src/m3_prep.py rebuild $K $CUR runs/m3_${TAG}.out runs/m3_${TAG}_tab.json > logs/m3_${TAG}_rebuild.log 2>&1 || { echo "$(date +%T) tour $r : rebuild invalide, on garde CUR"; cp $CUR runs/m3_${TAG}_tab.json; }
  if [ $((r % RM)) -eq 0 ]; then
    timeout $((TL + 600)) $PY src/rematch.py $K --start runs/m3_${TAG}_tab.json --save --time $TL --theta 40 --no-singletons --subsets --kbest 30 --out runs/m3_${TAG}_rm.json > logs/m3_${TAG}_rm.log 2>&1
    OUT=runs/m3_${TAG}_rm.json; WHAT=rematch
    [ -f $OUT ] || OUT=runs/m3_${TAG}_tab.json
  else
    timeout $((TL + 120)) $PY src/lns.py $K --lp --start runs/m3_${TAG}_tab.json --seed $((SEED * 1000 + r)) --mu $MU --kmax $KMAX --exact 300 --time $TL --save --save-every 60 --tag _${TAG} > logs/m3_${TAG}_lns.log 2>&1
    OUT=runs/lns_${K}_s$((SEED * 1000 + r))_${TAG}.json; WHAT=lns
  fi
  S2=$(score $OUT 2>/dev/null || echo 0)
  if [ "$S2" -ge "$S" ]; then cp $OUT $CUR; S=$S2; fi
  BEST=$(grep -A3 "\"$K\"" best/scores.json | grep -oE "\"score\": [0-9]+" | grep -oE "[0-9]+")
  echo "$(date +%T) tour $r : tabou $TB ; $WHAT -> $S2 ; courant $S gaspillage $(waste $CUR) ; best/ $BEST"
done
echo "$(date +%T) FIN courant $S ($CUR)"
