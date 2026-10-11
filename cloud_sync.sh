#!/usr/bin/env bash
# Synchronisation VM <-> cloud (cloud-host) : rapatrie best/instance_k.json du cloud et le passe par save_if_better ;
# pousse le best local vers le cloud (incoming/) et le fait valider là-bas. Usage : ./cloud_sync.sh "<k k ...>" <période_s>
set -uo pipefail
cd "$(dirname "$0")"
KS=${1:-6}; P=${2:-180}; PY=$HOME/venv/bin/python; TMP=${TMPDIR:-/tmp}/cloud_sync; mkdir -p $TMP
while true; do
  for k in $KS; do
    if rsync -q -az cloud-host:concours/best/instance_$k.json $TMP/cloud_best_$k.json 2>/dev/null; then
      r=$($PY src/save_if_better.py $k $TMP/cloud_best_$k.json --method "cloud cloud-host" 2>&1 | tail -n 1)
      case "$r" in *NOUVEAU*) echo "$(date +%T) $r";; esac
    fi
    rsync -q -az best/instance_$k.json cloud-host:concours/incoming/instance_$k.json 2>/dev/null && \
      r=$(ssh -o BatchMode=yes cloud-host "cd concours && ~/venv/bin/python src/save_if_better.py $k incoming/instance_$k.json --method 'vm'" 2>&1 | tail -n 1)
    case "$r" in *NOUVEAU*) echo "$(date +%T) cloud <- $r";; esac
  done
  sleep $P
done
