#!/usr/bin/env bash
# Plan de secours MIP6_PLAN §3.4 : rôles MIP agrégé avec offre effective (gaspillage supposé) -> réalisation (LNS init)
# -> gaspillage mesuré -> nouveaux rôles ; R tours ; puis alternance rematch/LNS (basin2.sh) depuis le meilleur réalisé.
# Usage : ./effective_loop.sh <k> <wf0> <wt0> <tours> <tag> "<fin UTC>"
set -uo pipefail
cd "$(dirname "$0")"
K=$1; WF=$2; WT=$3; R=$4; TAG=$5; END=$6; PY=$HOME/venv/bin/python; export HIGHS_THREADS=1
score() { $PY -c "
import sys; sys.path.insert(0,'src'); from save_if_better import evaluate
print(evaluate($K, open('$1').read())[0])"; }
BEST=""; BS=0
for r in $(seq 1 $R); do
  $PY src/lp_bound.py --shrink $WF $WT --mip-reduced 120 $K > logs/${TAG}_mip_r$r.log 2>&1
  ROLES=runs/mipr_${K}_s${WF}_${WT}.json
  AGG=$(grep -oE "MIP valeur [0-9]+" logs/${TAG}_mip_r$r.log | grep -oE "[0-9]+$")
  $PY src/lns.py $K --lp --init lp --roles $ROLES --exact 300 --time 300 --seed $((40 + r)) --mu 1 --kmax 20 --save --tag ${TAG}_r$r > logs/${TAG}_real_r$r.log 2>&1
  SOL=runs/lns_${K}_s$((40 + r))${TAG}_r$r.json
  S=$(score $SOL); read WF WT < <($PY src/waste_split.py $K $SOL)
  echo "$(date +%T) tour $r : rôles agrégés $AGG (offre -${WF}/-${WT} avant) -> réalisé+LNS 300 s $S ; gaspillage mesuré wf=$WF wt=$WT"
  if [ "$S" -gt "$BS" ]; then BS=$S; BEST=$SOL; fi
done
echo "$(date +%T) meilleur réalisé $BS ($BEST) -> alternance rematch/LNS jusqu'à $END"
./basin2.sh $K runs/mipr_${K}_s0.005_0.005.json $TAG "$END" $BEST
