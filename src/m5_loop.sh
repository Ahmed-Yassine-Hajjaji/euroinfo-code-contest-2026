#!/usr/bin/env bash
# Méthode 5 : boucle « fenêtres sur mesure » (src/m5_windows.py) -> LNS si des datasets/énergie ont été libérés.
# Usage : src/m5_loop.sh <k> <tag> <seed> <lns_s> "<fin UTC>" [source=best] [options m5_windows...]
#   source = best : repart de best/instance_k.json à chaque tour ; sinon : liste de fichiers (glob) parcourue en boucle.
set -uo pipefail
cd "$(dirname "$0")/.."
K=$1; TAG=$2; SEED=$3; TL=$4; END=$(date -d "$5" +%s); SRC=${6:-best}; shift 6 || shift $#
PY=$HOME/venv/bin/python; export HIGHS_THREADS=1
score() { $PY -c "
import sys; sys.path.insert(0,'src'); from save_if_better import evaluate
print(evaluate($K, open('$1').read())[0])"; }
r=0; files=(); i=0
[ "$SRC" != best ] && files=($SRC)
echo "$(date +%T) départ source=$SRC options=$*"
while [ $(date +%s) -lt $((END - TL - 60)) ]; do
  r=$((r + 1))
  if [ "$SRC" = best ]; then IN=best/instance_$K.json; else IN=${files[$((i % ${#files[@]}))]}; i=$((i + 1)); fi
  [ -f "$IN" ] || { sleep 30; continue; }
  OUT=runs/m5_${TAG}_win.json
  $PY src/m5_windows.py $K $IN $OUT --seed $((SEED * 100 + r)) "$@" > logs/m5_${TAG}_win.log 2>&1
  rc=$?
  L=$(grep -E "remplacements|aucune option" logs/m5_${TAG}_win.log | tail -1 | cut -c1-150)
  if [ $rc -eq 0 ]; then
    timeout $((TL + 120)) $PY src/lns.py $K --lp --start $OUT --seed $((SEED * 100 + r)) --mu 1 --kmax 20 --exact 300 --time $TL --save --save-every 60 --tag _${TAG} > logs/m5_${TAG}_lns.log 2>&1
    S2=$(score runs/lns_${K}_s$((SEED * 100 + r))_${TAG}.json 2>/dev/null || echo 0)
    echo "$(date +%T) tour $r [$IN $(score $IN)] : $L ; LNS $TL s -> $S2 ; best/ $(score best/instance_$K.json)"
  else
    echo "$(date +%T) tour $r [$IN $(score $IN)] : $L ; rien à exploiter"
    [ "$SRC" = best ] && sleep 120
  fi
done
echo "$(date +%T) FIN"
