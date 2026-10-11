#!/usr/bin/env bash
# Méthode 4 : boucle CP-SAT ciblé (créneaux à fort excès, échanges avec partenaires) -> LNS si des unités sont libérées.
# Repart de best/ à chaque tour. Usage :
#   src/m4_loop.sh <k> <tag> "<fin UTC>" [workers=4] [time_bloc=120] [partners=300] [pmode=release] [seed=0]
set -uo pipefail
cd "$(dirname "$0")/.."
K=$1; TAG=$2; END=$(date -d "$3" +%s); W=${4:-4}; T=${5:-120}; P=${6:-300}; PM=${7:-release}; SEED=${8:-0}
PY=$HOME/venv/bin/python; export HIGHS_THREADS=1
score() { $PY -c "
import sys; sys.path.insert(0,'src'); from save_if_better import evaluate
print(evaluate($K, open('$1').read())[0])"; }
CUR=runs/m4_${TAG}_cur.json; r=0
echo "$(date +%T) départ (workers $W, bloc ${T}s, partenaires $P, mode $PM)"
while [ $(date +%s) -lt $((END - 4 * T - 400)) ]; do
  r=$((r + 1)); cp best/instance_$K.json $CUR; S0=$(score $CUR)
  timeout $((4 * T + 300)) $PY src/m4_cp.py $K $CUR runs/m4_${TAG}_cp.json --hblock 100 --partners $P --pmode $PM --time $T \
    --workers $W --seed $((SEED + r)) --budget $((4 * T + 60)) > logs/m4_${TAG}_cp_r$r.log 2>&1
  FREED=$(grep -oE "libéré [0-9]+ u\. en" logs/m4_${TAG}_cp_r$r.log | tail -1 | grep -oE "[0-9]+" | head -1); FREED=${FREED:-0}
  if [ "$FREED" -gt 0 ]; then
    for j in $(seq 1 $W); do
      $PY src/lns.py $K --lp --start runs/m4_${TAG}_cp.json --seed $((SEED * 100 + r * 10 + j)) --mu $j --kmax $((10 * j)) --exact 300 \
        --time 300 --save --save-every 60 --tag _m4_${TAG}_r${r}_$j > logs/m4_${TAG}_lns_r${r}_$j.log 2>&1 &
    done
    wait
    BS=0; for j in $(seq 1 $W); do f=runs/lns_${K}_s$((SEED * 100 + r * 10 + j))_m4_${TAG}_r${r}_$j.json; [ -f $f ] && { s=$(score $f); [ "$s" -gt "$BS" ] && BS=$s; }; done
    echo "$(date +%T) tour $r : départ $S0, libéré $FREED u., LNS -> $BS ; best/ $(grep -A3 "\"$K\"" best/scores.json | grep -oE "\"score\": [0-9]+" | grep -oE "[0-9]+")"
  else
    echo "$(date +%T) tour $r : départ $S0, rien libéré ($(grep -c 'sans gain' logs/m4_${TAG}_cp_r$r.log) blocs sans gain, $(grep -c UNKNOWN logs/m4_${TAG}_cp_r$r.log) UNKNOWN)"
  fi
done
echo "$(date +%T) FIN"
