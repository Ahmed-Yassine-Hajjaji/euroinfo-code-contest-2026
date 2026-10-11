#!/bin/bash
# m10 : lance un run CP-SAT global sur AWS (ou local) en arrière-plan avec limite de temps.
# Usage : src/m10_launch.sh <tag> <durée max (s)> [args m10_cp.py...]
# Log : logs/m10_<tag>.log ; arrêt : pkill -f "^.*python src/m10_cp.py 6 --tag <tag>"
set -e
cd "$(dirname "$0")/.."
tag=$1; dur=$2; shift 2
PY=${PY:-$HOME/venv/bin/python}
setsid nohup timeout "$dur" "$PY" src/m10_cp.py 6 --tag "$tag" "$@" > "logs/m10_$tag.log" 2>&1 < /dev/null &
echo "lancé m10 $tag (pid $!), fin max dans $dur s, log logs/m10_$tag.log"
