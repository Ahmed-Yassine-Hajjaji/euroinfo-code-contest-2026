#!/usr/bin/env bash
# Surveillance des runs : ./status.sh   (ou en continu : watch -n 60 ./status.sh)
cd "$(dirname "$0")"
date; uptime
echo "processus : $(pgrep -fc 'venv/bin/python src/(lns|lp_bound).py') (attendu 12)"
python3 -c "
import json; s=json.load(open('best/scores.json'))
top={2:272322,3:523758,4:1031941,5:3786100,6:669672,7:5822560}
for k in sorted(s, key=int):
    sc=s[k]['score']; t=top.get(int(k))
    print(f'  inst {k}: {sc:>9}' + (f'   n°1 {t:>9}  écart {sc-t:+d}' if t else ''))
"
for f in logs/night_*.log; do printf '%-22s %s\n' "$f" "$(grep -E '^  t=|^FIN|^inst' "$f" | tail -n 1 | grep -oE 't=[0-9]+s|best=[0-9]+|gaspillage=[0-9]+|FIN.*|MIP.*' | tr '\n' ' ')"; done
git log --oneline | head -3
