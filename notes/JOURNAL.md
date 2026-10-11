# JOURNAL

## 2026-10-09 — Phase 1 (vérif) + Phase 2

### Mise en place
- Instances copiées dans `datasets/instance_k.json` (identiques aux fichiers Isograd `ctstfr00001_input_k.json`, md5 vérifiés).
- `test_solution.py`, `starter.py`, énoncés copiés à la racine depuis `starter_kit/`.
- `notes/ANALYSE.md` vérifiée contre l'énoncé et `test_solution.py`. Corrections : solution d'exemple de l'instance 1
  (générateur = modèle 3, pas 0), modèles « impossibles » réellement morts sur l'instance 4, absence de contrôle de
  bornes sur `modelMappings` dans le scoreur (indices négatifs acceptés → refusés par `save_if_better.py`).
- `src/save_if_better.py` : scoreur officiel + contrôle strict des indices, verrou fcntl, `best/scores.json`, commit git.

### starter.py (référence)
| inst | score | temps |
|---|---|---|
| 2 | 71 486 | 0 s |
| 3 | 167 236 | 0 s |
| 4 | 64 137 | 20 s |
| 5 | 0 (instance sautée, trop grosse) | — |
| 6 | 97 804 | 2 s |
| 7 | 0 (instance sautée, trop grosse) | — |

### Glouton `src/greedy.py` (partie A de l'analyse)
Priorité = valeur / (alpha·énergie/cap + Σ beta_t·données/offre_t), option plein tarif (libres seuls) vs demi-tarif
(copyrightés d'abord, remise gamma sur leur coût, générateurs si moins chers que les données), remplissage
« gros d'abord + plus petit finisseur + paires ». 0,1 s (inst 2) à 1,8 s (inst 7) par run.

| inst | params par défaut (beta = tension demande/offre) | recherche aléatoire 2 graines × 180 s | itérations/graine |
|---|---|---|---|
| 2 | 121 098 | **263 198** (s2) | ~5 600 |
| 3 | 283 612 | **523 483** (s2) | ~1 700 |
| 4 | 886 338 | **1 019 909** (s1) | ~1 200 |
| 5 | 3 487 127 | **3 646 547** (s2) | ~140 |
| 6 | 458 094 | **611 810** (s1) | ~540 |
| 7 | 3 822 109 | **5 631 084** (s1) | ~70 |

Constats :
- beta par défaut beaucoup trop élevé : les meilleurs runs ont beta ≈ 0,04–0,6 × tension (le prix de l'énergie domine).
- alpha = 0 n'apparaît jamais dans les meilleurs (même instance 5 où l'énergie n'est pas limitante : à vérifier).
- Paramètres exacts dans `best/scores.json` et les messages de commit.

## 2026-10-09 soir — LNS + LP
- Recherche aléatoire glouton 12 proc × 25 min (graines 101-103, bmin 0,01 bmax 1,5) : aucune amélioration.
- `src/lp_bound.py` : bornes LP 272 399 / 523 759 / 1 031 948 / 3 786 540 / 670 948 / 5 823 268 (inst 2-7).
- Init LP fidèle + LNS : 2 → 271 701 ; 3 → 523 637 ; 4 → 1 031 349 ; 5 → 3 783 879 ; 7 → 5 821 420 (30-40 s).
- Inst 6 : init LP 567 499 → LNS 30 s 650 291 → 2 LNS 10 min (s11 pscale 1,3 ; s12 temp 20 kmax 20) 661 863.
- Remplissage seul-vs-paire : pair_tries 40 ≈ 2000 (même résultat en 60 s).
- Inst 6 : gaspillage 2,0 % des données = l'essentiel de l'écart à la LP (voir RAPPORT.md).

## 2026-10-09 ~19h00-19h10 — Instance 6 : gaspillage
- `src/waste.py` : gaspillage avant = 2,004 % (502 872) sur le 6 ; 0,386 % (2) ; 0,003 % (4) ; 0,036 % (5).
- Subset-sum exact (`Pools.fill_exact`, bitset entier Python, validé vs force brute) : seul, aucun gain en 2 min
  (énergie aussi épuisée, et les égalités acceptées ne favorisent pas le faible gaspillage).
- Acceptation valeur − mu·gaspillage (mu = prix dual LP moyen des données) : **663 760** en 3 min (gaspillage 1,335 %).
  Variante gagnante : `--lp --mu 1 --kmax 20 --exact 300`, sans recuit.
- Réparation CP-SAT (`src/cpsat_repair.py`) : avec 4 threads × 5 s, réduit le gaspillage du sous-problème de ~37 % sans
  gain de valeur ; avec 1 thread trop lente → peu utile pour l'instant (gardée sur 2 processus de production).
- Inst 3 : 4 LNS 10 min → 523 753 (cible 523 758).
- Production 19h09 → ~21h10 : 12 LNS sur le 6 (`run.sh`, mu 0,5-3, kmax 10-40, dont 2 avec --cp 0.002), 1 LNS sur le 3
  (--target 523758). Puis 2, 4, 5 : 5 min chacune, mu=1, exact 300, sur le cœur restant.

## 2026-10-09 19h30-20h10 — MIP des rôles, nuit
- Inst 4 : MIP HiGHS 600 s → 1 031 935 (borne 1 031 947). Réalisation : exact≤300 → 1 028 974 ; exact tout (ordre
  croissant) → 941 223 (les petits datasets sont épuisés) ; exact tout ordre DÉCROISSANT → 1 031 935 (gaspillage 0).
- Inst 2 : MIP 300 s → 272 363 agrégé ; réalisation + LNS 120 s → 272 194.
- Inst 5 : MIP 600 s → 3 786 483 agrégé ; réalisation exact≤300 → 3 784 899 ; exact≤5000 → 3 785 149.
- Production 6 (12 proc, ~1 h) : 666 110 → 667 102. Arrêtée à 20:05 (pkill).
- MIP réduit (fixation LP 1e-6) : 5/6/7 optimaux en 48/3/12 s ; réalisation 7 → 5 821 820 ; 6 → 647 282 (échec).
- Nuit lancée 20:07 UTC (`night.sh "2026-10-10 07:00:00 UTC"`), 12 processus, voir RAPPORT.md.
- 20:20 : charge 17 au lieu de 12 : le MIP HiGHS (inst 4, scipy milp, threads non réglables) utilisait ~3 cœurs.
  Épinglé sur le cœur 13 (`taskset -a -cp 13 <pid>`) sans redémarrage → 12 processus à 100 %, CPU 86 %.
  La charge affichée reste ~16 (threads du MIP en file sur le cœur 13), ce n'est plus de la contention réelle.
  À corriger dans night.sh : lancer le MIP via `taskset -c 13`.

## 2026-10-10 matin — fin des runs de nuit, diagnostic instance 6
### Résultats de la nuit (20:07 → 07:00 UTC, 12 processus, tous validés via save_if_better)
| inst | départ soirée | fin de nuit | n°1 | écart | meilleur run |
|---|---|---|---|---|---|
| 2 | 272 194 | 272 299 | 272 318 | −19 | 2a/2b sync (mu 1 et 2) |
| 3 | 523 753 | 523 753 | 523 758 | −5 | cible non atteinte (le cœur a basculé sur 6f, sans gain) |
| 4 | 1 031 935 | 1 031 935 | 1 031 936 | −1 | MIP 4 h : pas mieux que 600 s |
| 5 | 3 785 149 | 3 785 853 | 3 786 096 | −243 | 5a (mu 1, exact 5000) |
| 6 | 667 102 | 667 690 | 669 632 | −1 942 | 6a (mu 1 kmax 20) ; recuit (6c, 6d) : aucun gain |
| 7 | 5 821 820 | 5 822 467 | 5 822 545 | −78 | 7a |

### Diagnostic §4.0 du plan MIP6 (`src/diag_roles.py`, 10 s)
- Rôles MIP (mipr_6) : Σ lb = 99,98 % de l'offre (marge ≈ 23 unités par créneau générateur). best/ utilise 4 998/5 000
  datasets, gaspillage 188 k = 0,75 % (F 65/créneau, Y 61/créneau) ; structure identique à la LP (F 1 645, Y 1 325, H 2).
- **L'hypothèse « partition » était fausse** : la phase H ne plaçait que 479/1 248 cibles à cause d'un bug de
  `State._pick_gen` : 4 essais max, et les 4 générateurs les moins chers (lb = 1, ub ≤ 650) n'ont plus de petit
  dataset → toutes les cibles suivantes échouaient. Correctif : on saute les fenêtres non remplissables
  (ub < plus petit dataset dispo) et `--gen-tries 8`. Rejeu : phase H 1 186/1 248, énergie 0,92 (au lieu de 0,41).
  Ce bug bridait aussi le LNS (insertion de cibles « allgen/half ») : LNS relancé corrigé sur 6 (10 proc), 5 et 7.
- Réalisation rôles → LNS 180 s : 659 845 (mipr_6) ; 661 950 (offre effective −0,5 %, valeur agrégée 669 551).
  Trop loin de best/ (667 690) : l'empaquetage glouton séquentiel laisse 1,8 % de gaspillage.
- Plan A (classes de taille, fenêtres conservatives) abandonné : la perte d'agrégation (centaines d'unités/créneau)
  dépasse la marge réelle (23/créneau). CP-SAT niveau dataset (type n, 423 créneaux F × 760 datasets, 60 s,
  2 threads) : 402/423 créneaux, 5 % de gaspillage → trop faible (`src/cp_pack.py`).
- Nouvelle piste exacte : `src/rematch.py` = MIP « paquets ↔ modèles » (paquets de best/ + datasets seuls, rôles,
  énergie, comptage générateurs/cibles). Inst 2 (theta 60) : 783 k colonnes, HiGHS n'a pas fini la LP racine en 120 s.
- `lp_bound.py --shrink wf wt` : offre effective (plan de secours §3.4). 6 : 0,5 % → 669 551 agrégé (6 s, réduit).

## 2026-10-10 07:30-08:00 — Ré-appariement exact « paquets ↔ modèles » (`src/rematch.py`) : ça marche
- Modèle : paquets de best/ (+ sous-ensembles 1..5 datasets, + datasets seuls en option), colonnes paquet→besoin
  (lb ≤ somme ≤ ub, libre si plein tarif) et paquet→générateur, rôles f/h/y/z, énergie, dataset ≤ 1 fois, comptage
  générateurs/cibles par type. Résolu avec **highspy + hint = solution courante** (scipy.milp : pas de hint, HiGHS ne
  trouvait aucune solution entière en 15 min). `--kbest K` : K besoins de meilleur coût réduit LP par paquet.
- Instance 6, 6 variantes en parallèle (1 thread chacune, 5-17 min) :
  | variante | colonnes | borne LP | résultat |
  |---|---|---|---|
  | theta 20, sans singletons | 490 k | 668 133 | 667 979 (crash HiGHS à 1 000 s, « dumped core ») |
  | theta 40, sous-ens., kbest 30, sans singl. | 562 k | 668 052 | **668 040 optimal** (10 min) |
  | theta 40, sous-ens., kbest 15, singl. | 294 k | 667 828 | 667 828 optimal (5 min) |
  | theta 40, tout (1,33 M col.) | 1 332 k | — | crash HiGHS en presolve |
  | theta 60, sous-ens., kbest 40, sans singl. | 745 k | 668 263 | 668 034 (gap 0,07 % à 1 500 s) |
  | theta 20, sous-ens., kbest 20, sans singl. | 377 k | 667 936 | 667 925 optimal (5 min) |
- Synergie avec le LNS (--sync) : le LNS repart de la solution ré-appariée et regagne ~+60 à chaque fois
  (nouveaux paquets → nouveau rematch). **6 : 667 690 → 668 101 en 1 h** (nuit entière : +588 en 11 h × 12 cœurs).
- Instance 2 : rematch riche (722 k col., 300 s) = 272 299 (borne 272 309) → rien à gagner par ré-appariement seul.
- Boucles lancées 08:00 : `loop_rematch.sh 6` sur 2 cœurs (variantes alternées, 600 s) + `run.sh 6 8 1500` (LNS 8 proc),
  LNS 5 et 7 sur 2 cœurs jusqu'à 12:00 UTC. HiGHS 1.15.1 plante parfois (core dump) sur les gros modèles : garder
  les variantes avec kbest (≤ 600 k colonnes).

## 2026-10-10 08:00-09:00 — boucles rematch ↔ LNS sur 6 ; essais sans gain
- 6 : 668 101 (08:00) → 668 285 (09:00) par les boucles (`loop_rematch.sh` ×2 + `loop_lns.sh` 8 proc). Gaspillage
  remonté à 0,87 % (le rematch gagne de la valeur en consommant plus).
- Sans gain : fusion des paquets de 12 solutions LNS (synchronisées → identiques) ; paquets échantillonnés près de lb
  (`--gen`) ; phase lexicographique min consommation (`--lex`, paquets fixés → rien) ; rematch 7 (= courant) ; 5 : +3.
- Génération de colonnes (`--cg`) : LP relâchée du master (30-270 s) → duaux datasets → meilleur paquet par besoin
  par sac à dos exact numpy (8 tables, 2 s). Mécanique validée (coûts réduits = col_dual HiGHS) mais LP très
  dégénérée : +2 pts par tour (668 285 → 668 294 en 5 tours, 12 k colonnes/tour, gain réduit max 780-1 800 sans effet).
  Le MIP final avec 414 k colonnes (10 min) ne bat pas le hint. Abandonné faute de temps (stabilisation duale à faire).
- LNS `--repack p` : ré-empaquetage exact de 2-3 créneaux du même type (+ petits datasets libres), énumération avec
  bornes. 12 800 essais / 60 s → 1 succès (3 unités) : la solution est localement optimale pour ces voisinages ; le
  gaspillage (72 u./créneau) ne se réduit qu'avec de grands voisinages.
- LNS `--exact 5000` : pas de différence mesurable vs `--exact 300`.

## 2026-10-10 09:00-10:40 — palier, second bassin, réalisation CP-SAT par blocs
- Boucles rematch ↔ LNS : 668 285 (09:00) → 668 428 (10:30), par petits pas (optimum de chaque variante = courant).
- Diversité : 4 LNS en recuit sans sync exportant leur état courant (`--dump-cur`, temp 5/15/40/100) → 1 079 à
  2 215 paquets différents de best/ ; rematch avec ces paquets (`--extra-sols`) = 668 327 = courant. Optimum local
  très robuste pour toute la famille « paquets fixés ».
- Second bassin (`basin.sh`, sans sync) : rôles MIP offre effective 0,5 % → réalisation corrigée 660 374 → tours
  rematch (300 s) + 3 LNS (300 s) : 664 514, 665 167, 665 618, 666 068 (+450/tour, décélère).
- 10:20 : délestage demandé (LNS sync 6 et 1 boucle rematch arrêtés). Cibles n°1 recalculées : 6 = 669 672.
- `src/realize_cp.py` (demande utilisateur) : rôles fixés par le MIP agrégé, affectation datasets → créneaux en CP-SAT
  par blocs de ~250 créneaux (×3 par type), hint = solution courante, abandons pénalisés (poids = part de valeur,
  valeur entière si les autres créneaux du modèle sont actifs), consommation à 0,005 pt/unité.
  Test depuis basin B (665 618) : +1 à +7 créneaux actifs par bloc, gaspillage souvent en hausse, FEASIBLE en 40 s ;
  assemblage 658 653 / **659 581** / 658 436 pour 0,4 / 0,5 / 0,6 % : moins que le bassin lui-même car les modèles
  hors rôles MIP (ajoutés par le LNS) sont perdus ; énergie 0,99 → LNS enchaîné pour comparaison équitable.

## 2026-10-10 12:25- — session parallèle « fin_* » (instances 3, 4, 2, 5 ; 2 cœurs, taskset 12-13)
- **Inst 3 : 523 753 → 523 758 = OPTIMUM PROUVÉ.** MIP des rôles (`lp_bound.py --mip 1200 3`) optimal en 30 s
  (valeur = borne = 523 758, relaxation valide car données non limitantes à 49 %) ; réalisation gloutonne
  `src/fin_realize.py` (fenêtres larges, datasets abondants) sans échec. Instance terminée.
- Inst 4 : décomposition de l'écart LP de best (`src/fin_gap.py`) : borne 1 031 947,98 − 1 031 935 = 12,98 =
  coûts réduits 4,67 + marges données libres 7,06 (F0 927 u., F1 50, F2 743, F3 238) + énergie 1,20.
  Fixation par coût réduit (cible 1 031 941) : 1 624 variables libres. CP-SAT 2 workers sur le cœur : rien en 4 min.
  LNS exact sur rôles (`src/fin_lns4.py`, sous-MIP HiGHS q = 10..600, départage ressources ou aléatoire) :
  0 mouvement accepté en ~100 k itérations (marges données trop serrées : tout échange casse une des 5 contraintes).
- Inst 2/5 : `src/fin_pack.py` (CP-SAT par blocs de créneaux libres + insertion de mono-modèles) : CP-SAT ne prouve
  rien même sur 17 datasets × 27 créneaux en 20 s → abandonné. Inst 5 : plus aucun mono-modèle libre (tout est utilisé).

## 2026-10-10 10:50-13:20 — cloud AWS, path relinking, CG stabilisée
- 12:05 : machine AWS 48 vCPU (`ssh cloud-host`). rsync du projet, venv (ortools 9.15, highspy, numpy, scipy).
  Lancé jusqu'à 23:30 UTC : 22 LNS sync + 4 boucles rematch + bassins B/C + modèle par blocs (3 offres, 2 passes).
  `cloud_sync.sh` sur la VM (3 min) : rapatrie best/ du cloud → save_if_better, pousse le best local → validé là-bas.
- Modèle par blocs 2 passes/60 s (AWS) : 661 189 / 660 075 / 660 832 (0,4/0,5/0,6 %) : jamais compétitif.
- Bassins (4, VM + AWS) : plateau ≈ 667 600-667 720 ; best/ 668 529 à 13:20 (boucles rematch AWS synchronisées).
- Path relinking (`lns.py --guide`, chemin borné : chaque modèle cible importé une fois avec ses paquets, perte
  tolérée 150 pts, puis LNS normal) depuis un pool d'élite de 10 solutions diversifiées (`src/elite.py`, distance =
  paquets non partagés ≈ 2 800-3 900 sur 3 000) : 14 paires × 20 min sur AWS → **aucun gain** (le LNS remonte au
  niveau de départ au mieux).
- CG stabilisée (`--cg-alpha 0.7 --cg-split 3`, 12 tours, LP 300 s) : la LP du master dépasse 300 s dès 500 k
  colonnes → duaux non optimaux, valeurs incohérentes (609 k-720 k). Non exploitable sans réduction du master.
- Conclusion 13:20 : tous les voisinages exacts/guidés testés redonnent la solution courante ; seuls les LNS
  (nouveaux paquets) + rematch progressent (+30-50/h). Instances 3 et 4 améliorées par ailleurs (523 758, 1 031 936).
- **Inst 4 : 1 031 935 → 1 031 936 → 1 031 937.** Clé : f <-> h ne change pas l'énergie → à modèles utilisés
  fixés, choix des tarifs = sac à dos 4-D sur les données libres (`src/fin_fh4.py`, HiGHS optimal 76 s : +1).
  Puis MIP HiGHS sur tout le cœur |coût réduit| <= 12 (1 735 modèles, `src/fin_alt4.py --steps c --q 99999`,
  2 400 s) : 1 031 937. Réalisation : `lns.py 4 --lp --init lp --roles <rôles> --exact 100000` (gaspillage 0).
  Écart LP restant : coûts réduits 9,5 + marges ~2,4.
- Inst 2 : rematch avec paquets générés aussi pour les fenêtres des candidats hors solution (`src/fin_rematch.py`,
  556 k col.) : optimal = 272 299 (borne 272 299) → l'empaquetage actuel est optimal pour ces paquets.
- Inst 5 : f/h à modèles fixés (`src/fin_fh.py`) : rôles 3 786 390 avec données libres pleines, +109 à
  consommation libre constante, mais (i) réalisation exacte de zéro + LNS 15 min = 3 785 728 ; (ii) application
  locale des 49 changements (`src/fin_switch.py`, 45 essais) toujours < best : l'excès piégé dans les autres
  créneaux n'est pas récupérable localement. Abandonné.
- Potentiel f/h à consommation libre constante : inst 2 +6, inst 7 +26 (rôles).
- Inst 4 : 2 tours supplémentaires du MIP du cœur (2 × 2 400 s) depuis 1 031 937 : pas mieux. Arrêté 15:25 UTC.
- Inst 2 : nouveaux bassins f/h (shrink 1 000 / 2 000 / 3 000) + réalisation exacte + LNS 10 min :
  272 180 / 272 144 / ~272 177 (best 272 299) → abandonné.
- Inst 7 : réalisation exacte de zéro des rôles actuels : --exact 100000 trop lent (> 25 min) ; --exact 3000 :
  5 821 077, gaspillage 229 k (vs 150 k dans best) → abandonné.
- 15:25 UTC : LNS --sync 25 min sur 2 (seed 9301, mu 2 kmax 40) et 7 (seed 7301, mu 1 kmax 20), cœurs 12-13.

## Finitions (session « fin_* », 2026-10-10 12:25 → 15:45 UTC)

### Runs de nuit lancés à 15:42 UTC (fin 07:00 UTC le 11/10)
- `lns.py 2 --lp --seed 9401 --mu 1 --kmax 20 --exact 300 --sync --until 07:00` → `logs/fin_night_2_s9401.log` (cœur 12)
- `lns.py 7 --lp --seed 7401 --mu 1 --kmax 20 --exact 300 --sync --until 07:00` → `logs/fin_night_7_s7401.log` (cœur 13)
- Sauvegarde automatique via save_if_better (commit si gain). Résultats : `best/scores.json` et `git log`.

### Ce qui a marché
**Instance 3 : 523 758 = optimum prouvé (terminée).** Les données ne sont pas limitantes (49 % utilisées) et il n'y a pas
de copyright : le problème se réduit au sac à dos énergie + générateurs. Le MIP des rôles (`lp_bound.py --mip 1200 3`)
est optimal en 30 s, avec une valeur égale à la borne. Les fenêtres sont larges (médiane 2 949) : la réalisation
gloutonne `src/fin_realize.py` remplit tout du premier coup. Le LNS plafonnait à 523 753 parce qu'il ne savait pas
réorganiser globalement le sac à dos d'énergie.

**Instance 4 : 1 031 935 → 1 031 937 (cible 1 031 941).**
1. Observation clé : passer un modèle de plein tarif (f) à demi-tarif (h), ou l'inverse, ne change NI l'énergie NI la
   consommation totale, seulement la consommation de données libres. À ensemble de modèles utilisés U fixé, le choix
   des tarifs est donc un sac à dos 4-D sur les données libres : `src/fin_fh4.py` (HiGHS, optimal en 76 s) → +1.
2. MIP HiGHS sur tout le cœur |coût réduit LP| ≤ 12 (exact pour les solutions ≥ 1 031 936), soit 1 735 modèles,
   hint = courant : `src/fin_alt4.py 4 --steps c --q 99999 --gapfix 12 --sub-time 2400` → +1. Deux tours de plus : rien.
3. Réalisation sans gaspillage : `lns.py 4 --lp --init lp --roles <rôles.json> --exact 100000 --save`.
- Diagnostic (`src/fin_gap.py 4`) : écart à la borne LP (1 031 947,98) = 11 pts, dont 9,5 de coûts réduits et ~2,4 de
  marges. Les petits voisinages échouent tous (fin_lns4 : 0 mouvement accepté sur ~100 k itérations, CP-SAT avec
  2 workers : rien) : avec des marges de données libres de 37 à 150 unités, tout échange casse une des 5 contraintes.
  Pour aller plus loin : MIP du cœur avec plus de threads / sur le cloud (cible : coûts réduits ≤ ~5).

### Diagnostic 2, 5, 7 : c'est le REGROUPEMENT des datasets en paquets qui bloque, pas les rôles
- Au niveau des rôles, il reste du gain (f/h à U fixé, `src/fin_fh.py`) :

  | inst | best | rôles, offre libre pleine | rôles, consommation libre constante | gaspillage libre actuel |
  |---|---|---|---|---|
  | 2 | 272 299 | 272 363 | 272 305 (+6) | ~14 400 u. ≈ 77 pts |
  | 5 | 3 785 868 | 3 786 390 | 3 785 977 (+109) | ~75 000 u. ≈ 405 pts |
  | 7 | 5 822 481 | 5 823 231 | 5 822 507 (+26) | ~150 000 u. ≈ 745 pts |

- Le gain des rôles suppose des créneaux remplis à lb près. Or le gaspillage est un excès de quelques unités
  par créneau (≈ 7 u./créneau sur le 5), réparti dans des milliers de créneaux plein tarif. Toutes les données libres
  sont déjà utilisées : un nouveau créneau plein tarif ne peut être rempli qu'en récupérant ces excès, donc en
  ré-empaquetant globalement.
- Ce qui a été tenté et pourquoi ça échoue :
  1. **Ré-appariement des paquets existants** (rematch, et `src/fin_rematch.py` qui génère aussi des paquets pour les
     fenêtres des modèles hors solution, 556 k colonnes) : sur le 2, optimal = 272 299 = borne. La bonne affectation
     des paquets aux modèles est déjà trouvée ; ce sont les paquets eux-mêmes qu'il faudrait changer.
  2. **Application locale des changements de tarif** (`src/fin_switch.py`, 45 essais sur le 5) : toujours sous best.
     Les datasets libérés par les modèles f→h ont bien la bonne somme, mais pas les bons sous-ensembles exacts pour
     les nouveaux créneaux ; une application partielle perd plus qu'elle ne gagne.
  3. **Réalisation exacte depuis zéro** (lns.py `--init lp --roles`, subset-sum exact décroissant), puis LNS :
     - 5 : gaspillage 66 k au lieu de 75 k, mais des créneaux finaux échouent → 3 785 712, puis LNS 15 min → 3 785 728 ;
     - 2 : marge 1 000 / 2 000 / 3 000 → 272 180 / 272 144 / ~272 177 en 10 min ;
     - 7 : `--exact 100000` trop lent (> 25 min) ; `--exact 3000` → 5 821 077, gaspillage 229 k.
     Un nouveau bassin part 150 à 1 400 pts plus bas et le LNS met des heures à le remonter.
  4. **CP-SAT par blocs de créneaux** (`src/fin_pack.py`) : il ne prouve rien, même sur 17 datasets × 27 créneaux en
     20 s. La formulation affectation x[d, créneau] est trop symétrique. Abandonné.
  5. **LNS --sync de 25 min** sur 2 et 7 : 0 gain (plateau).
- Piste non essayée, la plus prometteuse : ré-empaquetage par TYPE avec des colonnes = sous-ensembles exacts
  (somme dans [lb, lb + δ], δ ≈ 0-5) générés par subset-sum pour TOUS les créneaux plein tarif d'un type à la fois,
  puis un set-partitioning (HiGHS) qui maximise le nombre de créneaux exacts et libère l'excès en datasets entiers.
  Ensuite, insertion de mono-modèles ou passage h→f avec `fin_fh.py --keep-use X`. Il faudrait générer des colonnes
  bien plus « serrées » que `rematch --gen` (qui échantillonne au hasard dans [lb, lb + 60]).

### Scripts à réutiliser
- `src/fin_fh.py <k> [--keep-use X | --shrink S]` : tarifs f/h optimaux à U fixé (toutes instances). Sortie = rôles.
- `src/fin_fh4.py`, `src/fin_alt4.py` : instance 4 (sans générateurs) : tarifs 4-D, MIP exact sur le cœur, pas (a), (b), (c).
- `src/fin_mip4.py` (fixation par coût réduit + MIP), `src/fin_gap.py` (décomposition de l'écart LP).
- `lns.py <k> --lp --init lp --roles <rôles> --exact N` : réalisation exacte de rôles (N = 100000 pour le 4,
  ≤ 3000 pour le 7 sinon trop lent).
- `src/fin_realize.py` : réalisation gloutonne de rôles (OK pour le 3, données abondantes).
- `src/fin_switch.py`, `src/fin_rematch.py`, `src/fin_pack.py`, `src/fin_lns4.py`, `src/fin_cp4.py` : essais sans gain,
  gardés comme référence.
- Piège : highspy et ortools ne peuvent pas être importés dans le même processus (conflit de symboles) ; les LP des
  scripts CP-SAT passent par `scipy.optimize.linprog`.

## 2026-10-10 13:20-16:00 — AWS plein, grandes variantes, contrôle 16:00
- AWS (charge 48) : 32 LNS sur 6, 6 sur 5, 6 sur 7, 4 boucles rematch, bassins B/C, boucle « grandes variantes »
  (`loop_rematch_big.sh`, 8 threads, jusqu'à 891 k colonnes : 668 582 optimal à 14:40, ensuite = courant).
- CG stabilisée : 668 503 / 668 523 (hint 668 5xx) : rien. Relinking : rien. VM : jobs relancés 15:40 (6 LNS + 2 boucles).
- 6 : 668 534 (13:50) → 668 644 (15:00) → **668 666 (16:00)**, +20/h sur la dernière heure. Seuil 668 800 non atteint.
  5 : 3 785 872 (LNS AWS). Bassins : B 667 921, C 668 160 (plateau).

## 2026-10-10 16:10-18:15 — Instance 6 : trois méthodes « gaspillage » en parallèle (orchestration)
Départ commun figé `runs/start_m23_6.json` : 668 711, gaspillage 207 477 u. (0,760 % offre libre plein tarif / 0,827 % total).
Fin 18:10 : best/ **669 056**, gaspillage 171 028 u. (0,580 % / 0,682 %). +345 en 2 h (contre +20/h avant).
Cœurs libérés sur AWS à 16:10 : 28 LNS du 6, bassins B/C (plateau 667 9xx-668 1xx), `loop_rematch_big` (rien depuis 14:40),
6 LNS du 7 (rien depuis 09:37). VM : boucles rematch déplacées des cœurs 12-13 (réservés aux LNS de nuit 2/7) vers 10-11.

| méthode | cœurs | meilleur score propre | gaspillage | gain/h | verdict |
|---|---|---|---|---|---|
| 1 offre effective (`effective_loop.sh`, 3 variantes) | 12 | 667 634 (bassin, 18:04) | réalisation à 1,25-1,33 % libre / 1,7 % total | +60/tour, décélère ; −1 400 vs best | **abandonner** : la réalisation gloutonne gaspille 2× plus que best/, les rôles « offre effective » valent 666 9xx-667 2xx agrégé. Bug : nom du fichier de rôles (0,0171 ≠ 0,01710) → variantes 0,0075/0,009 passées en basin2 dès le tour 1. |
| 2 paquets 1-3 datasets exacts + set-partitioning HiGHS par type (`src/m2_pack.py`, `m2_loop.sh`) | ~15 (3 boucles × 5) | 668 874 (isolée) ; sync best/ : 0 sauvegarde | 191 017 u. (0,761 %) isolée | +97-100/h isolée ; 0 sur best/ | marche sur une solution lâche (−10 k u. en 4 min), mais LP à 0,03 % de marge sur best/ : **diversification seulement** (2 boucles). |
| 3 tabou datasets à rôles fixés, Rust (`src/m3_tabu/`, `m3_loop.sh` tabou 60-180 s → LNS 120-600 s / rematch) | 18 AWS + 2 VM | **669 056 = best/** (graines 1001-12001, 201xxx-208xxx dans le log AWS, premier test VM seed 7 : 668 741 → 668 840) | 171 028 u. (0,682 %) | +280 la 1re h, +32 la 2e | **à garder** : 85-170 k it/s ; mouvement clé = échange puis retrait ; synergie tabou → LNS (+130-170 par passage) → rematch. Plafond : la tabou ne retire plus rien une fois la solution polie (créneaux mono-dataset 1 517, excès concentré sur 275 créneaux). |

Relance nuit : `ssh cloud-host 'cd concours && src/m3_launch.sh 16 "2026-10-11 07:00:00 UTC" n best/instance_6.json 1'`
(+ 4 boucles rematch existantes ; option `src/m2_night.sh 6 2 "<fin>"` en diversification). Les boucles m3 du test s'arrêtent seules à 18:20 UTC.

## 2026-10-11 07:00 — Bilan de la nuit (10/10 18:30 → 11/10 07:00 UTC)
- Scores : 6 **669 137** (+81 depuis 18:30, dont +62 après 20:30 ; n°1 669 777, écart −640) ; 5 **3 785 933** (+51, LNS AWS
  jusqu'à 20:26 puis plateau) ; 7 5 822 483 (+2) ; 2, 4 inchangés (272 299, 1 031 937). Dernière sauvegarde sur le 6 : 05:43.
- m4 (CP-SAT ciblé sur les créneaux à fort excès, `src/m4_cp.py`, 2 variantes A/B, 7 cœurs AWS 18:27-20:23) : 12 + 7 tours,
  blocs |H| 60-70 créneaux × 300 partenaires × ~520 datasets (110 k vars) : toujours FEASIBLE sans gain, 0 u. libéré.
  m5 (fenêtres sur mesure, `src/m5_windows.py`) : 0 remplacement. **Les deux abandonnés à 20:30**, cœurs rendus à m3.
- Nuit AWS : 42 boucles m3 (14 sync n*, 14 élite e*, 7 m4r*, 7 m5r*) + 4 rematch ; VM : 10 m3 (5 et 2) + 2 rematch + 2 LNS (2, 7).
  Boucles sync : toutes finissent à 669 137 (gaspillage 163 4xx-164 0xx u., 0,652 %), la tabou ne libère plus rien ;
  boucles élite sans sync : 668 949-669 083, aucune ne dépasse best. **La tabou m3 est à plateau** : +62 en 10 h.
- 07:10 : tout est arrêté (fin programmée 07:00). Relancé jusqu'à 12:00 UTC : AWS 20 m3 (tags q1-q20, graines 201-220)
  + 4 rematch ; VM 2 rematch (cœurs 12-13). cloud_sync toujours actif.
- Décision : changement de méthode. m6 = mémétique sur le 6 (24 cœurs AWS, sous-agent, `src/m6_*`) ; m7 = MIP exact complet
  sur le 2 (cœurs 0-11 VM, sous-agent, `src/m7_*`, cible 272 322). Point de contrôle 09:30 UTC.

## 2026-10-11 07:15-09:00 — m6 (mémétique, inst 6) et m7 (MIP exact, inst 2), sous-agents
- **m6** (`src/m6_*`, `notes/M6.md`, 23 workers AWS depuis 08:11, fin 12:00) : 6 **669 137 → 669 153** (+6 direct m6 à 08:21,
  bascule h→f d'un modèle ; +10 par une boucle m3 sync repartie de l'enfant). 126 enfants en 65 min, 2 ont battu un parent.
  Constat : les 24 solutions à 669 137 de la nuit ont les mêmes rôles et le même gaspillage sur 3 types / 4 (plateau dégénéré).
  Croisement par chaînes d'éjection (rôles de A, paquets de B importés, sous-ensembles exacts) : enfant = score de A, 82 % des
  paquets de A gardés ; la tabou réduit ensuite le gaspillage dans 76 % des cas (14,5 % depuis une solution polie) ; mix 0,6 le
  meilleur. Gaspillage population 163 361 → 161 643. Échecs : MIP de recombinaison A ∪ B (rend A), rematch sur toute la
  population (496 k col., LP racine > 1 500 s). Énergie saturée (reste 2e8 / 1e15) : seuls gains possibles = bascules h→f.
- **m7** (`src/m7_*`, `notes/M7.md`, cœurs 0-11 VM) : 2 inchangé à 272 299. **Nouvelle borne valide 272 396** (MIP des rôles
  entier, 300 s) ; borne conditionnelle au gaspillage de best : 272 320. Maître entier sur 181 746 colonnes exactes : optimum
  du pool = 272 299 (prouvé, 718 s). CG : duaux dégénérés. Réalisation exacte par type depuis rôles réduits (HiGHS / CP-SAT,
  200 k binaires/type) : 271 678 / 272 138, toujours 1 créneau non réalisé par type. Verdict : 272 322 atteignable en théorie
  (rôles 272 372) mais pas avec ces méthodes ; ne plus investir en exact sur le 2. Reste : `m7_realize.py --shrink 3200` cœurs 6-11
  jusqu'à 11:55 (peu d'espoir).
- 08:59 : tué `apport` (core dump d'un rematch HiGHS crashé à 05:07, 1 cœur à 100 % depuis 3 h 50).

## 2026-10-11 09:30 — Point de contrôle et répartition de l'après-midi
| inst | 07:00 | 09:30 | n°1 | écart | méthode du dernier gain |
|---|---|---|---|---|---|
| 2 | 272 299 | 272 299 | 272 322 | −23 | (m7 : borne 272 396, rien de mieux) |
| 5 | 3 785 933 | 3 785 933 | 3 786 100 | −167 | LNS AWS (10/10 20:26) |
| 6 | 669 137 | **669 156** | 669 777 | −621 | m6 (+6) puis m3 sync (+13) |
| 7 | 5 822 483 | 5 822 483 | 5 822 560 | −77 | LNS (10/10 17:32) |
- AWS (48) : 23 workers m6 + 20 m3 sync + 4 rematch, fin 12:00 ; réinjection de best/ dans la population m6 toutes les 10 min.
- VM : m7 arrêté (plantage greedy.py IndexError dans m7_realize ; verdict « ne plus investir en exact sur le 2 »).
  Cœurs 0-11 → **m8** (sous-agent) : bascules h→f ciblées (besoin exact en datasets libres, libération dirigée), rapport 11:45.
  Cœurs 12-13 : 2 rematch jusqu'à 12:00.
- 09:45 : changement de cap (podium visé : il faut une rupture). AWS : m9 « empaquetage d'abord, rôles libres » (colonnes
  modèle + datasets exacts par besoin, sélection MIP/CP-SAT, 20 cœurs, `src/m9_*`) ; m10 CP-SAT global niveau dataset, hint
  complet = best/, réduit en fixant les rôles communs aux 10 meilleures du pool (16 cœurs, `src/m10_*`) ; 8 workers m6 + 4 rematch.
  Toutes les boucles m3 synchronisées (q1-q20) arrêtées (plafond). VM : m8 (0-11), 2 rematch (12-13). Point 13:30 UTC.

## 2026-10-11 09:45-12:00 — m8 / m9 / m10 (sous-agents interrompus à 09:55 par la limite de session, calculs autonomes en cours)
- **m8** (`src/m8_*`, notes/M8.md, VM 0-11) : scan de 516 solutions : 45 admettent une bascule hc→f (+4 à +8) mais max 669 143 < best.
  Tabou restreinte à un type depuis best : 0 dataset libéré (18 runs). Set-partitioning par type sur les paquets observés dans la
  population (143-188 k colonnes/type) : marge LP 4-5 k u./type mais aucun entier meilleur (HiGHS 900 s, CP-SAT 600 s FEASIBLE/UNKNOWN).
  3 boucles tournent jusqu'à 18:00 (A/C CP-SAT, B HiGHS) : 0 gain à 12:00.
- **m9** (`src/m9_mip.py`, `m9_loop.sh`, notes/M9.md, 14 workers AWS × 2 000 s, fin 18:00) : colonnes = modèle + paquets exacts
  (3 334 modèles candidats θ=10, 1 604 générateurs, ~157 k colonnes). **Borne LP racine 669 688** (famille 173 k col.) : le n°1
  (669 777) est quasiment à la borne LP de cette famille ; `--fix-gen` borne 669 583. Simplex dual très lent (572 s racine) ;
  B&B : aucune amélioration (tours à 669 156). Résultat clé : l'écart à la LP vient de la granularité des paquets, pas des rôles.
- **m10** (`src/m10_cp.py`, notes/M10.md, AWS 8+4×2 workers, tranches 1 200 s avec hint, fin ~16:30) : modèle exact vérifié
  (hint décodé = 669 156), 266 k vars (98 modèles libres) / 392-402 k (par type) ; borne CP-SAT +9 000-15 000, **0 gain** en 7 tours.
  Verdict de l'agent : arrêter si rien à 12:00 et rendre les cœurs.
- 12:00 : relance automatique OK (8 m3 r1-r8 graines 401-408 + 4 rematch, fin 18:00). m6 terminé. best/6 = 669 156 depuis 08:56.
- 12:30 : décisions utilisateur : m10 arrêté (0 gain en 7 tours) ; m9 renforcé par un plongeon LP/RINS (sous-agent, `src/m9_rins*`,
  22 cœurs AWS = 16 de m10 + 6 libres : fixer les colonnes LP ≥ 0,95/0,9/0,8 et celles communes LP ∩ best, MIP réduit exact en
  tranches courtes, fin 18:00) ; m8, m3 r1-r8, rematch inchangés.

## 2026-10-11 13:30 — Point de contrôle (aucun gain depuis 08:56 ; best/6 = 669 156)
| méthode | cœurs | tours / runs | résultat | verdict |
|---|---|---|---|---|
| m6 mémétique (07:30-12:00) | 23→8 AWS | 280 enfants | +6 direct, +13 via m3 sync | relance de la tabou, pas de recombinaison ; terminé |
| m7 MIP exact inst 2 | 12 VM | 8 modèles | 272 299 ; borne valide 272 396 | abandonné |
| m8 bascules h→f / set-partitioning par type | 12 VM | 17 tours × 3 boucles | 0 (marge LP 4-5 k u./type, pas d'entier) | plateau |
| m9 MIP colonnes exactes (14 workers) | 14 AWS | 77 MIP de 2 000 s | 0 ; borne LP 669 688 | plateau B&B |
| m9 RINS HiGHS (22 workers, 12:49-13:20) | 22 AWS | ~60 sous-problèmes | 0 ; voisinages ≥ 0,5 prouvés sans gain | → CP-SAT (dernier essai, fin 15:30) |
| m10 CP-SAT global | 16 AWS | 7 tours × 1 200 s | 0, borne +9-15 k | arrêté 12:30 |
| m3 r1-r8 + rematch (12:00-) | 12 AWS + 2 VM | 13 tours | 0 | fond |
Conclusion : toutes les formulations exactes (rôles libres ou fixés) convergent vers 669 156 ou n'y trouvent rien ; la LP
(669 688) laisse 530 pts dans la granularité des paquets, que ni HiGHS ni CP-SAT ne récupèrent en < 30 min.
- 13:50 : RINS CP-SAT sans résultat (UNKNOWN / = hint en 900 s, bornes 674-678 k). **AWS arrêté** : tous les processus tués,
  dernière synchro best/ via save_if_better (7 instances : rien de mieux), scan des 7 629 fichiers runs/+incoming/ d'AWS (44 cœurs) :
  max par instance = best (2 : 272 299, 5 : 3 785 933, 6 : 669 156, 7 : 5 822 483). Logs/notes AWS copiés dans runs/aws_final/.
  cloud_sync arrêté. Machine AWS supprimable. VM : m8 (0-11) jusqu'à 18:00 UTC.
