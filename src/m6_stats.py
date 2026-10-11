#!/usr/bin/env python3
"""m6 : résumé des logs des workers (logs/m6_w*.log) : enfants, gaspillage avant/après tabou, distances, succès."""
import glob, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rows = []
for fn in sorted(glob.glob(os.path.join(ROOT, "logs", "m6_w*.log"))):
    for l in open(fn):
        m = re.search(r"tour (\d+) : p(\d+)\((\d+)\) x p(\d+)\((\d+)\) dAB=(\d+) mix=([\d.]+) -> enfant (\d+) dA=(\d+) gasp (\d+) ; tabou \[(\d+) -> (\d+).*?-> (\d+) gasp (\d+) ; lns -> (\d+).*?final (\d+) gasp (\d+) dmin=(\d+) ; (.*?) ;", l)
        if m:
            g = m.groups()
            rows.append(dict(sA=int(g[2]), sB=int(g[4]), dAB=int(g[5]), mix=float(g[6]), s0=int(g[7]), dA=int(g[8]), w0=int(g[9]), wt0=int(g[10]), wt1=int(g[11]), s1=int(g[12]), w1=int(g[13]), s2=int(g[14]), s3=int(g[15]), wC=int(g[16]), dmin=int(g[17]), act=g[18]))
n = len(rows)
if not n:
    print("aucun tour"); sys.exit()
print(f"enfants {n} ; score enfant = A : {sum(r['s0']==r['sA'] for r in rows)} ; > max(parents) : {sum(r['s3']>max(r['sA'],r['sB']) for r in rows)} ; meilleur enfant {max(r['s3'] for r in rows)}")
print(f"distance enfant-A moy {sum(r['dA'] for r in rows)/n:.0f} (min {min(r['dA'] for r in rows)}, max {max(r['dA'] for r in rows)}) ; créneaux 2997 -> paquets de A conservés moy {100*(1-sum(r['dA'] for r in rows)/n/2/2997):.0f} %")
print(f"gaspillage enfant = A : {sum(r['w0']==r['wt0'] for r in rows)}/{n} ; tabou réduit le gaspillage : {sum(r['w1']<r['w0'] for r in rows)}/{n} (moy -{sum(r['w0']-r['w1'] for r in rows)/n:.0f} u.) ; final < min(parents) : {sum(r['act'].find('GASP')>=0 for r in rows)}")
print(f"gaspillage min final {min(r['wC'] for r in rows)} ; LNS gain score : {sum(r['s2']>r['s1'] for r in rows)} ; rematch gain : {sum(r['s3']>r['s2'] for r in rows)} ; insérés {sum('rempl' in r['act'] for r in rows)} rejetés {sum('rejet' in r['act'] for r in rows)}")
for mx in sorted({r['mix'] for r in rows}):
    rs = [r for r in rows if r['mix'] == mx]
    print(f"  mix {mx}: {len(rs)} enfants, dA moy {sum(r['dA'] for r in rs)/len(rs):.0f}, tabou réduit {sum(r['w1']<r['w0'] for r in rs)}/{len(rs)}, baisse moy {sum(r['w0']-r['w1'] for r in rs)/len(rs):.0f}")
