#!/usr/bin/env bash
# Autonome (sans Claude) : à 20:35 UTC, pour m4 et m5 : si aucune sauvegarde dans best/ (log git VM et AWS depuis 18:20),
# arrête leurs boucles sur AWS et relance 7 boucles m3 (instance 6) à leur place jusqu'à 07:00 UTC.
# Usage : setsid nohup ./auto_2035.sh > logs/auto_2035.log 2>&1 < /dev/null &
set -uo pipefail
cd "$(dirname "$0")"
T=$(date -d "2026-10-10 20:35:00 UTC" +%s); END="2026-10-11 07:00:00 UTC"
echo "$(date -u +%T) attente jusqu'à 20:35 UTC"
while [ $(date +%s) -lt $T ]; do sleep 30; done
cat > /tmp/auto_kill_relaunch.sh <<'EOR'
cd ~/concours; M=$1; END=$2; B=$3
pkill -f "^bash src/${M}_"; sleep 2
P=$(pgrep -f "src/${M}_|_${M}_|runs/${M}_"); echo "processus $M tués : $(echo $P | wc -w)"; kill -TERM $P 2>/dev/null; sleep 10
P=$(pgrep -f "src/${M}_|_${M}_|runs/${M}_"); [ -n "$P" ] && kill -KILL $P 2>/dev/null
V=("120 300 50 1e-7 16 1 20 3" "120 300 50 1e-7 16 1 20 1000" "60 300 50 1e-7 16 1 20 3" "60 240 30 1e-7 16 2 40 1000"
   "120 300 100 1e-7 16 1 20 3" "120 300 50 3e-7 16 1 20 1000" "90 300 70 1e-7 24 1 20 3")
NE=$(ls runs/elite_6/e*.json | wc -l)
for i in 1 2 3 4 5 6 7; do
  set -- ${V[$((i - 1))]}
  if [ $i -le 4 ]; then S=best/instance_6.json; SY=1; else S=runs/elite_6/e$(( (B + i) % NE )).json; SY=0; fi
  setsid nohup src/m3_loop.sh 6 ${M}r$i $((B + i)) $1 $2 "$END" $3 $4 $5 $6 $7 $8 $S $SY > logs/m3_${M}r$i.log 2>&1 < /dev/null &
  echo "boucle m3 ${M}r$i depuis $S (sync $SY)"
done
EOR
scp -q /tmp/auto_kill_relaunch.sh cloud-host:/tmp/auto_kill_relaunch.sh
B=400
for M in m4 m5; do
  nv=$(git log --since="2026-10-10 18:20" --format=%s | grep -c "\[$M")
  na=$(ssh -o BatchMode=yes cloud-host "cd concours && git log --since='2026-10-10 18:20' --format=%s | grep -c '\[$M'")
  echo "$(date -u +%T) $M : sauvegardes best/ VM=$nv AWS=$na"
  if [ "${nv:-0}" -eq 0 ] && [ "${na:-0}" -eq 0 ]; then
    echo "$(date -u +%T) $M : rien -> arrêt et relance de 7 boucles m3 jusqu'à $END"
    ssh -o BatchMode=yes cloud-host "bash /tmp/auto_kill_relaunch.sh $M '$END' $B"
  else
    echo "$(date -u +%T) $M : a amélioré best/ -> conservée"
  fi
  B=$((B + 10))
done
ssh -o BatchMode=yes cloud-host "cd concours; uptime; echo boucles m3 : \$(pgrep -fc '^bash src/m3_loop.sh')"
echo "$(date -u +%T) FIN"
