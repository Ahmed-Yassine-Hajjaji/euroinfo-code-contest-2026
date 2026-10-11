# M9 RINS — plongeon guidé par le LP sur le modèle à colonnes m9 (instance 6) — 2026-10-11, 12:30 → 18:00 UTC

## Idée
Le MIP m9 (≈157-173 k colonnes « paquet exact → besoin », 19 k lignes) a une borne LP racine de 669 580-669 690,
≈ +430-530 au-dessus de best/ (669 156), mais le B&B de HiGHS n'améliore jamais l'incumbent (racine simplex : 572 s).
RINS = résoudre un MIP réduit en fixant les variables sur lesquelles la LP et la solution courante **s'accordent**.

## Constat déterminant (test VM, modèle θ5 k5 fix-gen, 76 k colonnes, LP IPM = 669 561)
La solution IPM (point intérieur, sans crossover) est quasi entière sur les RÔLES (9 fractionnaires sur 4 849 f/h actifs)
mais très fractionnaire sur les colonnes de paquets : parmi les 1 677 colonnes de best/ (modèles entraînés), 206 ont une
valeur LP ≥ 0,999, 516 ≥ 0,5, 1 212 > 1e-6 ; hors best/, 40 colonnes ≥ 0,999, 5 009 > 1e-6. La fixation « LP ≥ seuil »
demandée initialement (mode `--mode lp`) n'a donc presque aucune prise (≈ 60 colonnes hors best/), et fixer
« support LP ∩ best/ » revient à fixer presque tout best/ → infaisable avec la coupure objectif ≥ courant + 1.
→ Mode par défaut `--mode rins` (accord) : colonnes hors best/ de valeur LP ≤ eps0 fixées à 0 (≈ 57 k sur 65 k),
colonnes de best/ de valeur LP ≥ seuil fixées à 1, rôles fixés quand |LP − best| ≤ 1 − seuil (option `--fix-roles`),
part aléatoire `--frac` laissée libre. Le MIP réduit après presolve : **3 779 lignes × 5 784 colonnes**, racine LP en 12 s
(contre 572 s pour le modèle complet), borne du réduit = borne LP complète (669 560,5 : le voisinage contient l'optimum LP).

## Fichiers (nouveaux uniquement)
| fichier | rôle |
|---|---|
| `src/m9_rins.py` | construction du modèle (copie de `m9_mip.main`, fonctions importées de `m9_mip`), LP racine IPM mise en cache `runs/m9_rins_lp_<hash>.npz` (hash du modèle), tours RINS, décodage, `save_if_better` |
| `src/m9_rins_loop.sh <w> "<fin UTC>" [total s] [threads]` | boucle autonome : modèle selon w mod 3, paramètres RINS selon w mod 4, graine modèle = w (cache LP réutilisé), processus de `total` s puis relance depuis best/ courant |
| `logs/m9_rins_w*.log`, `runs/m9_rins_<tag>_r<n>.json` | logs et solutions améliorantes |

Options principales de `m9_rins.py` : paramètres de génération de m9 (`--theta --k1 --k2 --k3 --eps1/2/3 --hcols --kcur --cross --fix-gen`),
`--lp-solver ipm --crossover 0 --lp-threads`, `--thresholds 0.9,0.7` (cycle), `--frac 1.0,0.9` (cycle), `--eps0 1e-6,1e-3` (cycle),
`--fix-roles 0/1`, `--lp-one 0.95` (fixer aussi à 1 les colonnes hors best/ de valeur LP ≥ 0,95), `--rc0 x` (fixer à 0 par coût réduit),
`--cutoff 0/1` (ligne objectif ≥ courant + 1 : sans incumbent HiGHS cherche directement une amélioration ; avec 0, le hint best/
est réalisable dans le réduit et HiGHS part d'un incumbent), `--slice` (temps HiGHS par tour), `--total` (durée du processus).
Le processus s'arrête de lui-même si best/ change ailleurs (la boucle shell repart du nouveau best/).

## Variantes de production (AWS, 22 workers × 1 thread, 12:49 → 18:00 UTC)
| w mod 3 | modèle | colonnes | LP IPM (1 thread) |
|---|---|---|---|
| 0 | θ5 k10 ε300/5/0 | 173 k | 669 688, ≈ 60 s |
| 1 | θ10 k15 ε500/10/2 `--fix-gen` | 157 k | 669 584, 19 s |
| 2 | θ5 k8 ε300/5/1 `--fix-gen --hcols 0.1` | 93 k | 669 577, 9-13 s |

| w mod 4 | seuils | frac | eps0 | cutoff | rôles fixés | tranche |
|---|---|---|---|---|---|---|
| 0 | 0,9 / 0,7 | 1,0 / 0,9 | 1e-6 / 1e-3 | 1 | oui | 300 s |
| 1 | 0,9 / 0,5 | 1,0 / 0,85 | 1e-6 | 0 | oui | 600 s |
| 2 | 0,95 / 0,8 | 0,9 / 0,7 | 1e-4 | 1 | non | 400 s |
| 3 | 0,9 | 1,0 / 0,8 | 1e-6 / 1e-2 | 0 | non | 600 s |

- Lancement : `ssh cloud-host 'cd concours && for w in $(seq 1 22); do setsid nohup src/m9_rins_loop.sh $w "2026-10-11 18:00:00 UTC" 2400 1 > logs/m9_rins_w$w.log 2>&1 < /dev/null & done'`
- Arrêt : `ssh cloud-host 'pkill -f "^/bin/bash src/m9_rins_loop.sh"; pkill -f "^/home/user/venv/bin/python src/m9_rins.py"'`
- Suivi : `ssh cloud-host 'cd concours && grep -h "TOUR\|AMÉLIO\|save_if" logs/m9_rins_w*.log | tail -40; grep -A3 "\"6\"" best/scores.json'`
- Déploiement : `rsync -az src/m9_rins* cloud-host:concours/src/`

## Résultats
(voir tableau des tours ci-dessous, complété au fil de l'eau)

### Premiers tours (AWS, 12:50 → 13:00 UTC ; MIP réduit = colonnes libres après fixation, avant presolve)
| worker | modèle (col.) | seuil | frac | eps0 | cutoff | rôles fixés | fixées à 1 | fixées à 0 | libres | statut | valeur | borne réduit | temps |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| w4/w8/w16 (mod 4 = 0) | 93 k fix-gen | 0,9 | 1,0 | 1e-6 | 1 | 11 477 | 1 587 | 70 669 | 9 177 | limite temps, 14 nœuds | — (aucune réalisable ≥ 669 157) | 669 576 | 300 s |
| w12 (mod 4 = 0) | 173 k | 0,9 | 1,0 | 1e-6 | 1 | 11 394 | 826 | 144 094 | 17 127 | limite temps, 0 nœud | — | 669 600 | 300 s |
| w1/w5/w13 (mod 4 = 1) | 157 k / 93 k fix-gen | 0,9 | 1,0 | 1e-6 | 0 | 11 479 | 1 585 | 68 734 | 11 130 | limite temps, 391 nœuds | 669 156 (= hint, décodage validé) | 669 576 | 600 s |
| w3/w7/w15 (mod 4 = 3, v1) | 93-157 k | 0,9 | 1,0 | 1e-6 | 0 | 0 | 1 574 | 69 888 | 21 461 | limite temps, 2 nœuds | 669 156 (= hint) | 669 576 | 600 s |
| w2/w6/w10 (mod 4 = 2, v1) | 93-173 k | 0,95 | 0,9 | 1e-4 | 1 | 0 | 630-1 426 | 66-134 k | 24-38 k | limite temps, 0 nœud | — | 669 576-669 649 | 400 s |
| VM test (θ5 k5, 76 k) `--roles-lp 1` | 76 k | 0,9 | 1,0 | 1e-6 | 0 | 11 581 (= LP arrondie) | 1 320 | 56 732 | 6 690 | limite temps, 0 nœud | — | 669 393 | 100 s |
Lecture : le MIP réduit (3,8 k lignes × 5,8-10 k colonnes après presolve) a sa racine en ~12 s et conserve la borne LP
complète, mais HiGHS n'y trouve pas de solution entière améliorante en 300-600 s : l'écart d'intégrité est dans
l'empaquetage (set packing), pas dans les rôles. Avec les rôles arrondis de la LP (`--roles-lp`), la borne du réduit
tombe à 669 393 et aucun empaquetage réalisable n'est trouvé en 100 s.
13:00 UTC : variantes 2 et 3 resserrées (2 : seuils 0,5/0,3, rôles fixés, coupure, 600 s ; 3 : seuil 0,7, incumbent, 1 500 s),
11 workers relancés (anciens logs `logs/m9_rins_w*_v1.log`).

### 13:00-13:10 UTC (tours 2-3 des workers initiaux, tour 1 des variantes resserrées)
| variante | seuil | frac | libres | statut | temps |
|---|---|---|---|---|---|
| mod 4 = 2 (resserrée) | 0,5 / 0,3 | 1,0 | 5,4-11 k | **Infaisable prouvé** (aucune amélioration dans ce voisinage) | 5-157 s |
| mod 4 = 0, tour 2 | 0,7 | 1,0 | 8-17 k | limite temps, 0-6 nœuds, pas de solution | 300 s |
| mod 4 = 0, tour 3 | 0,9 | 0,9 | 16-32 k | limite temps, 0 nœud | 300 s |
Lecture : les voisinages « colonnes de best/ de valeur LP ≥ 0,5 fixées » ne contiennent aucune amélioration (preuve en
quelques secondes) ; les améliorations, si elles existent dans la famille de colonnes, exigent de défaire des paquets de
best/ que la LP ne soutient qu'à 0,5-0,9. Les voisinages de 8-10 k colonnes libres (seuil 0,7-0,9, frac 1) sont la bonne
taille mais 300 s ne suffisent pas (racine ≈ 12-60 s, puis heuristiques) → tranches de 900-1 500 s à privilégier.

## 13:12 UTC — bascule vers CP-SAT (consigne : dernier essai, fin programmée 15:30 UTC)
Les 22 workers HiGHS sont arrêtés (aucune amélioration ; voisinages ≥ 0,5 prouvés sans amélioration, voisinages 8-10 k
colonnes libres non résolus en 300-600 s). Nouveaux fichiers :
| fichier | rôle |
|---|---|
| `src/m9_rins_cp.py` | parent : modèle m9 + LP (cache) + fixation RINS (fonctions de `m9_rins.py`), export du MIP réduit (colonnes libres, bornes de lignes diminuées de l'activité des colonnes fixées) en npz dans `runs/m9_rins_cp/`, appel du sous-processus CP-SAT, reconstruction, décodage, `save_if_better` ; `--until "<fin UTC>"` |
| `src/m9_rins_cp_solve.py` | enfant ortools : variables booléennes, lignes entières (ligne énergie mise à l'échelle 1e9, lignes triviales supprimées), objectif entier, hint complet = best/, `num_workers`, limite de temps ; résultat en npz |
| `src/m9_rins_cp_loop.sh <id> "<fin>" <cp|highs> <workers> <variante modèle 0-2> <seuils> [cutoff] [tranche]` | boucle de relance d'un sous-problème (CP-SAT ou HiGHS) |
Test VM (θ5 k5, 76 k col., seuil 0,8, 2 workers, 60 s) : MIP réduit 6 511 variables × 4 466 lignes (objectif sur 92 rôles libres), CP-SAT UNKNOWN en 60 s.

Répartition AWS (22 cœurs, 13:16 → 15:30 UTC) :
| log | solveur | workers | modèle | seuils (cycle) | coupure | tranche |
|---|---|---|---|---|---|---|
| `logs/m9_rins_cp1.log` | CP-SAT | 8 | 157 k fix-gen (LP 669 584) | 0,8 / 0,7 / 0,9 | oui | 900 s |
| `logs/m9_rins_cp2.log` | CP-SAT | 8 | 93 k fix-gen (LP 669 577) | 0,7 / 0,8 / 0,9 | oui | 900 s |
| `logs/m9_rins_cp3.log` | CP-SAT | 4 | 173 k (LP 669 695) | 0,7 / 0,8 | oui | 900 s |
| `logs/m9_rins_highs4.log` | HiGHS | 1 | 157 k fix-gen | 0,8 / 0,7 | oui | 1 800 s |
| `logs/m9_rins_highs5.log` | HiGHS | 1 | 93 k fix-gen | 0,8 / 0,7 | non (incumbent) | 1 800 s |
- Lancement : voir les 5 lignes `setsid nohup src/m9_rins_cp_loop.sh ...` (commande de 13:16 dans ce fichier / rapport).
- Arrêt : `ssh cloud-host 'pkill -f "^/bin/bash src/m9_rins_cp_loop.sh"; pkill -f "^/home/user/venv/bin/python src/m9_rins"; pkill -f "m9_rins_cp_solve.py"'`
- Suivi : `ssh cloud-host 'cd concours && grep -h "TOUR\|\[cp\]\|AMÉLIO\|save_if" logs/m9_rins_cp*.log logs/m9_rins_highs*.log | tail -20; grep -A3 "\"6\"" best/scores.json'`

### Résultats CP-SAT / HiGHS (AWS, 13:16 → 13:50 UTC)
| sous-problème | solveur | modèle | seuil | coupure | libres (col. × lignes) | statut | valeur | borne | temps |
|---|---|---|---|---|---|---|---|---|---|
| cp2 r1 | CP-SAT 8 w. | 93 k fix-gen | 0,7 | oui | 8 510 × 4 499 | UNKNOWN (aucune solution) | — | 674 046 (faible) | 900 s |
| cp1 r1 | CP-SAT 8 w. | 157 k fix-gen | 0,8 | oui | 20 399 × 4 697 | UNKNOWN | — | 674 673 | 900 s |
| cp3 r1, r2 | CP-SAT 4 w. | 173 k | 0,7 / 0,8 | oui | 13 306 × 7 187 | UNKNOWN | — | 678 232 | 900 s |
| cp2 r1 (relancé 13:33 sans coupure) | CP-SAT 8 w. | 93 k fix-gen | 0,7 | non | 8 510 × 4 499 | FEASIBLE = hint | 669 156 (validé) | 673 745 | 900 s |
| highs4 r1 | HiGHS 1 th. | 157 k fix-gen | 0,8 | oui | 16 626 | limite temps, 1 289 nœuds, aucune solution | — | 669 582 | 1 800 s |
| highs5 r1 | HiGHS 1 th. | 93 k fix-gen | 0,8 | non | 11 105 | limite temps, 930 nœuds | 669 156 (= hint) | 669 577 | 1 800 s |
Lecture : CP-SAT ne trouve aucune solution entière améliorante dans ces voisinages (avec coupure : UNKNOWN, borne CP
très faible ≈ 674-678 k, sa relaxation est bien plus lâche que la LP) ; sans coupure il conserve l'incumbent sans
l'améliorer en 900 s ; HiGHS idem en 1 800 s (930-1 289 nœuds). 13:33 : cp1 et cp2 relancés sans coupure (hint réalisable,
LNS internes de CP-SAT) ; cp3 garde la coupure. Tout s'arrête à 15:30 UTC (`--until`, timeouts).
Bilan provisoire : la borne LP du modèle à colonnes (+420 à +530) n'est pas atteignable par plongeon/RINS en pratique ;
l'écart d'intégrité est dans l'empaquetage (set packing dégénéré), et les voisinages où best/ est largement fixé sont
prouvés sans amélioration. Les gains restants viennent plutôt des LNS/m3 (quelques points par heure).
