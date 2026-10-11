#!/usr/bin/env bash
# Méthode 2 : boucle ré-empaquetage à rôles fixés (m2_pack.py, 4 procs) -> exploitation (4 LNS + 1 rematch en
# parallèle, 300 s, --save via save_if_better) -> meilleur des candidats -> on recommence, jusqu'à une heure de fin.
# Usage : src/m2_loop.sh <k> <start.json> <tag> "<fin UTC>" <seed> [block=120] [kcol=200] [delta=20] [pack_time=240]
set -uo pipefail
cd "$(dirname "$0")/.."
K=$1; START=$2; TAG=$3; END=$(date -d "$4" +%s); SEED=$5; BLOCK=${6:-120}; KCOL=${7:-200}; DELTA=${8:-20}; PT=${9:-240}
PY=$HOME/venv/bin/python; export HIGHS_THREADS=1
score() { $PY -c "
import sys; sys.path.insert(0,'src'); from save_if_better import evaluate
print(evaluate($K, open('$1').read())[0])" 2>/dev/null || echo 0; }
CUR=runs/m2_${TAG}_cur.json; cp "$START" $CUR; CS=$(score $CUR)
echo "$(date +%T) départ $START score $CS gaspillage $($PY src/waste.py $K $CUR | grep -oE 'gaspillage [0-9]+ ')"
i=0; SYNC=${10:-0}
while [ $(date +%s) -lt $((END - PT - 360)) ]; do
  i=$((i + 1)); S=$((SEED * 1000 + i * 10))
  if [ "$SYNC" = 1 ]; then BS0=$(score best/instance_$K.json); CS=$(score $CUR); if [ "$BS0" -gt "$CS" ]; then cp best/instance_$K.json $CUR; echo "$(date +%T) sync : repart de best/ ($BS0 > $CS)"; fi; fi
  timeout $((PT + 300)) $PY src/m2_pack.py $K --start $CUR --out runs/m2_${TAG}_p$i.json --block $BLOCK --kcol $KCOL \
    --delta $DELTA --time $PT --sub-time 12 --threads 1 --procs 4 --seed $S --quiet > logs/m2_${TAG}_p$i.log 2>&1
  P=runs/m2_${TAG}_p$i.json; [ -f $P ] || P=$CUR
  W=$(grep -oE "gaspillage [0-9]+ -> [0-9]+" logs/m2_${TAG}_p$i.log | tail -1)
  MUS=(1 0.5 2 1); KM=(20 10 40 20)
  for j in 0 1 2 3; do
    timeout 420 $PY src/lns.py $K --lp --start $P --seed $((S + j)) --time 300 --save --save-every 60 \
      --mu ${MUS[$j]} --kmax ${KM[$j]} --exact 300 --tag m2_$TAG > logs/m2_${TAG}_l${i}_$j.log 2>&1 &
  done
  timeout 900 $PY src/rematch.py $K --start $P --save --time 300 --theta 40 --no-singletons --subsets --kbest 30 \
    --out runs/m2_${TAG}_r$i.json > logs/m2_${TAG}_r$i.log 2>&1 &
  wait
  BEST=$P; BS=$(score $P)
  for f in runs/lns_${K}_s$((S))m2_$TAG.json runs/lns_${K}_s$((S+1))m2_$TAG.json runs/lns_${K}_s$((S+2))m2_$TAG.json \
           runs/lns_${K}_s$((S+3))m2_$TAG.json runs/m2_${TAG}_r$i.json; do
    [ -f $f ] || continue; s=$(score $f); if [ "$s" -gt "$BS" ]; then BS=$s; BEST=$f; fi
  done
  cp $BEST $CUR
  echo "$(date +%T) tour $i : $W ; exploitation -> $BS ($BEST) ; best/ $(grep -A3 '"'$K'"' best/scores.json | grep -oE '"score": [0-9]+')"
done
echo "$(date +%T) fin : $CUR score $(score $CUR)"
