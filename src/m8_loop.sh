#!/usr/bin/env bash
# m8 : boucle autonome de ré-empaquetage par type sur les paquets de la population (CP-SAT ou HiGHS), enchaînée
# (la sortie à gaspillage réduit devient le départ suivant ; resynchro sur best/ s'il est meilleur), bascules hc->f
# appliquées et sauvegardées via save_if_better (--save dans m8_popcp/m8_popmip).
# Usage : src/m8_loop.sh <tag> <cœurs ex. 0-3> <cp|highs> <time_s> "<fin UTC>" [types ex. "3 2 1 0"] [target 0/1]
set -uo pipefail
cd "$(dirname "$0")/.."
TAG=$1; CORES=$2; SOLVER=$3; TT=$4; END=$(date -d "$5" +%s); TYPES=${6:-"3 2 1 0"}; TGT=${7:-0}
NW=$(( $(echo $CORES | awk -F- '{print $2-$1+1}') ))
PY=$HOME/venv/bin/python; export HIGHS_THREADS=$NW
POOL="runs/m8/pop/*.json runs/m8/pop2/*.json runs/m6_*c*.json runs/m3_*_cur.json runs/m8_*_r*.json best/instance_6.json"
CUR=runs/m8_${TAG}_cur.json; cp best/instance_6.json $CUR
score() { $PY -c "import sys; sys.path.insert(0,'src'); from save_if_better import evaluate; print(evaluate(6, open('$1').read())[0])"; }
S=$(score $CUR); r=0
declare -A NEED=([3]=2229 [2]=2354 [1]=59 [0]=0)
echo "$(date +%T) départ $S ($SOLVER $NW threads, $TT s, types $TYPES, target $TGT)"
while [ $(date +%s) -lt $((END - TT - 120)) ]; do
  for T in $TYPES; do
    r=$((r + 1)); [ $(date +%s) -lt $((END - TT - 120)) ] || break 2
    BS=$(grep -A3 '"6"' best/scores.json | grep -oE '"score": [0-9]+' | grep -oE '[0-9]+')
    if [ "$BS" -gt "$S" ]; then cp best/instance_6.json $CUR; S=$BS; echo "$(date +%T) sync best/ $BS"; fi
    OUT=runs/m8_${TAG}_r${r}.json; TG=0; [ "$TGT" = 1 ] && TG=${NEED[$T]}
    if [ "$SOLVER" = cp ]; then
      timeout $((TT + 900)) taskset -c $CORES $PY src/m8_popcp.py 6 --start $CUR --pool $POOL --types $T --time $TT --workers $NW --seed $r --target $TG --out $OUT --save --method "m8 loop $TAG r$r cp type$T" > logs/m8_${TAG}_run.log 2>&1
    else
      timeout $((TT + 900)) taskset -c $CORES $PY src/m8_popmip.py 6 --start $CUR --pool $POOL --types $T --time $TT --threads $NW --out $OUT --save --method "m8 loop $TAG r$r highs type$T" > logs/m8_${TAG}_run.log 2>&1
    fi
    RES=$(grep -hE "^type|m8_pop|bascule" logs/m8_${TAG}_run.log | tr '\n' ' ' | cut -c1-400)
    W0=$($PY src/waste_split.py 6 $CUR | cut -d' ' -f2)
    if [ -f $OUT ]; then W1=$($PY src/waste_split.py 6 $OUT | cut -d' ' -f2); S1=$(score $OUT); if [ "$S1" -ge "$S" ] && [ "$(echo "$W1 < $W0" | bc)" = 1 ]; then cp $OUT $CUR; S=$S1; fi; else W1=-; fi
    [ -f ${OUT%.json}_bas.json ] && { S2=$(score ${OUT%.json}_bas.json); [ "$S2" -gt "$S" ] && { cp ${OUT%.json}_bas.json $CUR; S=$S2; }; }
    echo "$(date +%T) tour $r type $T : $RES | gasp $W0 -> $W1 ; courant $S ; best/ $(grep -A3 '"6"' best/scores.json | grep -oE '"score": [0-9]+' | grep -oE '[0-9]+')"
  done
done
echo "$(date +%T) FIN courant $S"
