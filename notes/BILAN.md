# BILAN — Concours « IA responsables » (Euro-Information, 9-11 octobre 2026)

> **Scores définitifs** (`best/scores.json`, relevés le 2026-10-11 19:15 UTC ; tous les calculs arrêtés, dernier gain 11/10 08:56 UTC).
> Tous les scores cités ont été validés par `test_solution.py` via `src/save_if_better.py` et commités dans `best/`
> (399 commits « best instance », 432 commits au total).

## 0. Le problème en trois lignes
Choisir des modèles à entraîner sous un plafond d'énergie (sac à dos) et affecter à chacun des datasets (chaque dataset
au plus une fois) pour que, pour chaque type de données requis (n, t, i, c), la somme des tailles tombe dans
[lowerBound, upperBound]. Un modèle mono-besoin peut servir de **générateur** et couvrir entièrement un besoin d'un
autre modèle (sa valeur est perdue, son énergie compte). Score = Σ valeurs des modèles entraînés, valeur **// 2** si le
modèle utilise un dataset copyrighté ou un générateur (malus non cumulables). Classement : chaque instance vaut
1 000 000 points au prorata du meilleur score. Détails : `notes/ANALYSE.md`.

Vocabulaire utilisé dans tout le bilan : **rôles** = pour chaque modèle, plein tarif (f), demi-tarif (h), générateur (y),
besoin couvert par générateur (z) ou inutilisé ; **créneau** = couple (modèle, type) à remplir ; **paquet** = ensemble de
datasets affecté à un créneau ; **gaspillage** = Σ (somme du paquet − lb) sur les créneaux remplis par des datasets.

---

## 1. Tableau final

| inst | score final | n°1 (classement) | écart | points de classement (calculés) | borne supérieure connue | nature de la borne | écart à la borne | méthode du meilleur score |
|---|---|---|---|---|---|---|---|---|
| 1 | **12 946** | 12 946 | 0 | 1 000 000 | 12 946 | optimum prouvé (énumération exhaustive) | 0 | solution d'exemple (optimale) |
| 2 | **272 299** | 272 322 | −23 (−0,008 %) | 999 916 | 272 396 | MIP des rôles entier, valide (`src/m7_bound.py`, 300 s) ; LP 272 399 | 97 (0,036 %) | LNS nuit (`lns.py`, seed 2001, mu 1) |
| 3 | **523 758** | 523 758 | 0 | 1 000 000 | 523 758 | **optimum prouvé** (MIP des rôles = borne, 30 s) | 0 | MIP rôles HiGHS + `fin_realize.py` |
| 4 | **1 031 937** | 1 031 941 | −4 (−0,0004 %) | 999 996 | 1 031 947 (LP 1 031 947,98) | relaxation LP des rôles (`lp_bound.py`) | 10 (0,001 %) | sac à dos f/h 4-D (`fin_fh4.py`) + MIP du cœur (`fin_alt4.py`) + réalisation exacte |
| 5 | **3 785 933** | 3 786 100 | −167 (−0,004 %) | 999 956 | 3 786 540 | relaxation LP des rôles | 607 (0,016 %) | LNS sync sur AWS (10/10 20:26) |
| 6 | **669 156** | 669 777 | −621 (−0,093 %) | 999 073 | 670 948 | relaxation LP des rôles (empaquetage parfait) ; LP du modèle à colonnes 1-3 datasets : 669 688-669 830 (borne de famille, non valide pour le problème complet) | 1 792 (0,27 %) | m6 mémétique (+6) puis boucle m3 tabou → LNS → rematch (+13), 11/10 08:56 |
| 7 | **5 822 483** | 5 822 560 | −77 (−0,001 %) | 999 987 | 5 823 268 | relaxation LP des rôles | 785 (0,013 %) | LNS sync (seed 7401, 10/10 17:32) |

Total calculé : **6 998 927 / 7 000 000** points (perte 1 073, dont 927 sur l'instance 6). Les valeurs n°1 sont
celles relevées dans `notes/JOURNAL.md` (point 09:30 UTC le 11/10) et `notes/RAPPORT.md`. Les écarts à la borne LP
ne sont pas des écarts à l'optimum : sur le 2, la borne valide 272 396 est elle-même hors de portée (voir §3.14).

### Référence de départ (starter.py)
| inst | starter | glouton (2 graines × 180 s) | final | gain vs starter |
|---|---|---|---|---|
| 2 | 71 486 | 263 198 | 272 299 | ×3,8 |
| 3 | 167 236 | 523 483 | 523 758 | ×3,1 |
| 4 | 64 137 | 1 019 909 | 1 031 937 | ×16 |
| 5 | 0 (instance sautée) | 3 646 547 | 3 785 933 | — |
| 6 | 97 804 | 611 810 | 669 156 | ×6,8 |
| 7 | 0 (instance sautée) | 5 631 084 | 5 822 483 | — |

---

## 2. Courbe de progression (jalons tirés de `notes/progression.csv`)

### Instance 2 (15 améliorations, 09/10 18:24 → 10/10 01:15)
| date (UTC) | score | méthode |
|---|---|---|
| 09/10 18:24 | 263 198 | glouton, recherche aléatoire de paramètres |
| 09/10 18:34 | 271 427 | glouton guidé LP + LNS 1 s |
| 09/10 18:37 | 271 701 | init LP fidèle + LNS 40 s |
| 09/10 19:14 | 272 096 | LNS (seed 4242) |
| 09/10 19:53 | 272 194 | réalisation du MIP des rôles + LNS |
| 09/10 20:09 | 272 274 | LNS mu 1 (nuit) |
| 10/10 01:15 | 272 299 | LNS sync seed 2001 — **plateau définitif** (36 h sans gain malgré m7, rematch, bassins) |

### Instance 3 (6 améliorations)
| date | score | méthode |
|---|---|---|
| 09/10 18:24 | 523 483 | glouton |
| 09/10 18:56 | 523 637 | LNS 30 s |
| 09/10 18:58 | 523 753 | LNS (seed 72187) |
| 10/10 12:27 | 523 758 | MIP des rôles HiGHS 30 s optimal + réalisation gloutonne — **optimum prouvé** |

### Instance 4 (5 améliorations)
| date | score | méthode |
|---|---|---|
| 09/10 18:24 | 1 019 909 | glouton |
| 09/10 18:37 | 1 031 349 | init LP fidèle + LNS 30 s |
| 09/10 19:46 | 1 031 935 | MIP des rôles 600 s + subset-sum exact décroissant (gaspillage 0) |
| 10/10 12:56 | 1 031 936 | sac à dos f/h 4-D (`fin_fh4.py`, 76 s) |
| 10/10 13:48 | 1 031 937 | MIP du cœur |coût réduit| ≤ 12 (`fin_alt4.py`, 2 400 s) |

### Instance 5 (48 améliorations)
| date | score | méthode |
|---|---|---|
| 09/10 18:24 | 3 646 547 | glouton |
| 09/10 18:37 | 3 783 879 | init LP fidèle + LNS 30 s |
| 09/10 20:04 | 3 785 149 | réalisation MIP rôles (exact ≤ 5 000) |
| 09/10 23:47 | 3 785 765 | LNS nuit seed 5001 |
| 10/10 08:05 | 3 785 864 | rematch θ 30 (seul gain du rematch sur le 5 : +3 → 3 785 864) |
| 10/10 14:52 | 3 785 872 | LNS AWS |
| 10/10 18:53 | 3 785 928 | LNS seed 502003 (6 LNS sync AWS) |
| 10/10 20:26 | 3 785 933 | LNS AWS — plateau ensuite |

### Instance 6 (299 améliorations, 75 % du total)
| date | score | méthode |
|---|---|---|
| 09/10 18:24 | 611 810 | glouton |
| 09/10 18:35 | 650 291 | init LP fidèle + LNS 30 s |
| 09/10 18:48 | 661 863 | LNS 10 min |
| 09/10 19:08 | 663 760 | LNS acceptation valeur − mu·gaspillage, subset-sum exact |
| 09/10 20:04 | 667 102 | 12 LNS en parallèle (1 h) |
| 10/10 06:21 | 667 690 | nuit, 12 LNS (+588 en 11 h) |
| 10/10 07:39 | 668 040 | **rematch** θ 40 optimal (10 min) |
| 10/10 10:19 | 668 428 | boucles rematch ↔ LNS |
| 10/10 16:00 | 668 666 | idem + AWS 48 vCPU (+20/h) |
| 10/10 17:57 | 669 056 | **tabou m3 (Rust) → LNS → rematch** (+345 en 2 h) |
| 11/10 05:43 | 669 137 | 42 boucles m3 de nuit (+81 en 11 h) |
| 11/10 08:56 | 669 156 | m6 mémétique (+6) puis m3 sync (+13) — plateau depuis |

### Instance 7 (25 améliorations)
| date | score | méthode |
|---|---|---|
| 09/10 18:24 | 5 631 084 | glouton |
| 09/10 18:34 | 5 821 194 | glouton guidé LP (duaux HiGHS) |
| 09/10 20:07 | 5 821 820 | réalisation MIP réduit des rôles |
| 09/10 20:39 | 5 822 396 | LNS seed 7001 |
| 10/10 04:37 | 5 822 467 | LNS nuit |
| 10/10 17:32 | 5 822 483 | LNS sync seed 7401 — plateau |

Lecture d'ensemble : 95 % du gain est acquis dans les 2 premières heures (glouton + LP + LNS) ; les 40 heures
suivantes ont servi à gratter 0,1-0,5 % par instance, presque exclusivement sur l'instance 6.

---

## 3. Méthodes testées, dans l'ordre chronologique

### 3.1 Glouton paramétré (`src/greedy.py`) — 09/10 18:24
- **Idée** : priorité d'un modèle = valeur_effective / (α·énergie/cap + Σ_t β_t·lb_t/offre_t) (prix de ressources
  façon lagrangien). Deux options par modèle : plein tarif (datasets libres seuls) ou demi-tarif (copyrightés d'abord,
  remise γ, générateur si moins cher que les données). Remplissage « gros d'abord + plus petit finisseur + paires ».
- **Paramètres** : α, β_t, γ, gq tirés au hasard (recherche aléatoire 2 graines × 180 s, 70 à 5 600 itérations/graine).
- **Gain** : 263 198 / 523 483 / 1 019 909 / 3 646 547 / 611 810 / 5 631 084 (inst 2-7), 0,1-1,8 s par run.
- **Diagnostic** : β par défaut (tension demande/offre) trop élevé, les meilleurs runs ont β ≈ 0,04-0,6 × tension :
  le prix de l'énergie domine. Une recherche prolongée (12 proc × 25 min) n'a rien ajouté.
- **À refaire** : passer directement à l'initialisation par LP (§3.2), le glouton pur a vécu 10 minutes.

### 3.2 Relaxation LP des rôles et LNS (`src/lp_bound.py`, `src/lns.py`) — 09/10 18:34 → fin du concours
- **Idée** : LP HiGHS sur les rôles (x_m ∈ [0,1], énergie, offre de données par type, générateurs) → borne supérieure
  et duaux (prix de l'énergie et des données). « Init LP fidèle » = réaliser les modèles à x = 1 ; puis LNS : détruire
  k modèles (aléatoires / pire ratio / même type) avec leurs générateurs, reconstruire en glouton bruité (options
  plein / demi / tout-générateur), accepter si score ≥ courant, retour arrière exact sinon.
- **Fichiers** : `lp_bound.py` (170 lignes, `--mip`, `--shrink`), `lns.py` (760 lignes : `--lp --mu --kmax --exact
  --sync --start --init lp --roles --guide --repack --dump-cur`), `run.sh`, `loop_lns.sh`, `night.sh`.
- **Gain** : bornes LP 272 399 / 523 759 / 1 031 948 / 3 786 540 / 670 948 / 5 823 268 ; init LP + LNS 30-40 s :
  271 701 / 523 637 / 1 031 349 / 3 783 879 / 650 291 / 5 821 420. Jusqu'au bout, le LNS est resté la seule méthode
  qui progresse sur 2, 5, 7 (plateaux 272 299 / 3 785 933 / 5 822 483).
- **Deux ajouts décisifs** (09/10 19:08) : acceptation **valeur − mu·gaspillage** (mu = prix dual moyen des données) et
  **subset-sum exact** par bitset (`Pools.fill_exact`, validé contre force brute) : inst 6 661 863 → 663 760 en 3 min,
  gaspillage 2,0 % → 1,3 %. Préférer les gros datasets en subset-sum (ordre décroissant) : inst 4 réalisée à
  gaspillage 0 (1 031 935) là où l'ordre croissant donnait 941 223.
- **Bug important** (corrigé 10/10 07:07) : `State._pick_gen` n'essayait que 4 générateurs et les 4 moins chers
  (lb = 1, ub ≤ 650) n'avaient plus de petit dataset → la phase « tout-générateur » ne plaçait que 479/1 248 cibles.
  Correctif (`--gen-tries 8`, fenêtres non remplissables sautées) : 1 186/1 248.
- **Échecs** : recuit simulé (temp 5-100) jamais meilleur que l'acceptation en plateau ; `--repack` (ré-empaquetage exact
  de 2-3 créneaux) : 1 succès pour 12 800 essais ; `--exact 5000` = `--exact 300`.
- **À refaire** : écrire le LNS directement en Rust (le Python plafonne à ~1 itération/s sur le 7) et mettre dès le
  départ l'objectif « gaspillage » dans l'acceptation.

### 3.3 MIP des rôles et réalisation (`lp_bound.py --mip`, `src/fin_realize.py`) — 09/10 19:30
- **Idée** : rendre entier le modèle des rôles (HiGHS via scipy.milp, 300-600 s) puis « réaliser » : affecter des
  datasets à chaque créneau par subset-sum exact.
- **Gain** : inst 4 1 031 935 (borne 1 031 947) ; inst 3 **optimum prouvé 523 758** (30 s, données non limitantes à
  49 %, fenêtres larges, réalisation gloutonne sans échec) ; inst 7 5 821 820 (MIP réduit par fixation LP 1e-6, 12 s).
- **Échec** : inst 6, réalisation 647 282 / 659 845 (l'empaquetage glouton séquentiel laisse 1,8 % de gaspillage, la
  marge réelle est de 23 unités par créneau) ; inst 2/5 : rôles 272 363 / 3 786 483 agrégés, réalisation 272 194 /
  3 785 149, sous le LNS après quelques heures.
- **Diagnostic** : la décomposition rôles → empaquetage est exacte quand les données sont abondantes (3) ou les
  fenêtres très étroites mais le gaspillage nul atteignable (4) ; elle casse dès que l'offre de données est saturée.

### 3.4 Réparation CP-SAT et CP-SAT par blocs (`src/cpsat_repair.py`, `src/cp_pack.py`, `src/realize_cp.py`) — 09/10 → 10/10 10:38
- `cpsat_repair.py` (4 threads × 5 s) : −37 % de gaspillage sur un sous-problème, aucun gain de valeur.
- `cp_pack.py` (type n, 423 créneaux × 760 datasets, 60 s, 2 threads) : 402/423 créneaux, 5 % de gaspillage.
- `realize_cp.py` : rôles du MIP agrégé, blocs de ~250 créneaux, hint = solution courante, abandons pénalisés.
  Assemblage 658 653 / 659 581 / 658 436 (offre effective 0,4 / 0,5 / 0,6 %) : sous le bassin de départ (665 618).
- **Diagnostic** : la formulation x[dataset, créneau] est trop symétrique pour CP-SAT ; constat répété avec m4, m7,
  m8, m10 (§3.12, 3.14, 3.16, 3.19).

### 3.5 Rematch : MIP de ré-appariement « paquets ↔ modèles » (`src/rematch.py`, `loop_rematch.sh`) — 10/10 07:30
- **Idée** : garder les paquets de la solution courante (plus leurs sous-ensembles de 1 à 5 datasets, plus
  optionnellement les datasets seuls), et résoudre exactement : quel paquet va à quel besoin (lb ≤ somme ≤ ub, libre si
  plein tarif) ou à quel générateur, avec rôles f/h/y/z, énergie, dataset ≤ 1 fois, générateurs ≥ cibles par type.
  `--kbest K` : K besoins de meilleur coût réduit LP par paquet (support θ).
- **Implémentation** : 579 lignes, **highspy avec hint = solution courante** (scipy.milp n'a pas de hint : HiGHS ne
  trouvait aucune solution entière en 15 min). Options `--cg --gen --lex --extra-sols --start`.
- **Gain** : inst 6, 6 variantes en parallèle (1 thread, 5-17 min) : 667 690 → **668 040 optimal** (θ 40,
  sous-ensembles, kbest 30, 562 k colonnes, 10 min). Alterné avec le LNS (`--sync`), le LNS regagne +60 à chaque
  tour → 668 101 en 1 h, puis +30-50/h : 668 428 à 10:30, 668 666 à 16:00 (avec AWS). Rematch sur le 2 : 272 299 =
  borne de ses paquets ; sur le 5 : +3 ; sur le 7 : = courant.
- **Limites** : HiGHS 1.15.1 plante (core dump) au-delà de ~1 M colonnes (variante « tout », 1,33 M) ; garder
  ≤ 600 k colonnes. Grandes variantes multi-thread (`loop_rematch_big.sh`, 891 k colonnes, 8 threads) : un seul gain
  (668 582 à 14:40).
- **Diagnostic** : à paquets fixés, l'optimum est vite atteint (chaque variante = courant) ; le gain vient de
  l'alternance avec un producteur de nouveaux paquets (LNS, puis tabou m3). Méthode la plus rentable du 10/10 matin.

### 3.6 Bassins et offre effective (`basin.sh`, `basin2.sh`, `effective_loop.sh`, `lp_bound.py --shrink`) — 10/10 09:00 → 18:00
- **Idée** : repartir d'autres rôles (MIP des rôles avec offre de données réduite de 0,4-0,6 % pour anticiper le
  gaspillage), réaliser, puis tours rematch + LNS, pour trouver un second bassin d'attraction.
- **Résultat** : bassin B 660 374 → 666 068 en 4 tours (+450/tour, décélère) ; plateau 667 600-668 160 (VM + AWS, 4
  bassins) ; `effective_loop.sh` (3 variantes, 12 cœurs, 2 h) : 667 634, réalisation à 1,7 % de gaspillage (2× best).
  Bug de nommage (0,0171 ≠ 0,01710) qui a mélangé deux variantes dès le tour 1.
- **Diagnostic** : un nouveau bassin part 1 400 à 8 000 pts sous best et met des heures à le remonter ; les rôles
  « offre effective » valent 666 9xx-667 2xx agrégés. Abandonné le 10/10 18:04.

### 3.7 Path relinking et pool d'élite (`lns.py --guide`, `src/elite.py`) — 10/10 12:55
- **Idée** : chemin borné entre deux solutions d'élite (chaque modèle cible importé une fois avec ses paquets, perte
  tolérée 150 pts), puis LNS normal. Pool de 10 solutions diversifiées (distance = paquets non partagés, 2 800-3 900
  sur 3 000).
- **Résultat** : 14 paires × 20 min sur AWS : **aucun gain**, le LNS remonte au mieux au niveau de départ.
- **Diagnostic** : les solutions d'élite sont des réarrangements à gaspillage constant (vérifié plus tard par m6 : mêmes
  rôles, même gaspillage sur 3 types / 4) ; relier deux points du même plateau n'apporte rien.

### 3.8 Génération de colonnes (`rematch.py --cg`, `--cg-alpha`, `--cg-split`) — 10/10 09:00 et 12:58
- **Idée** : LP relâchée du master (paquets ↔ besoins) → duaux des datasets → meilleur paquet par besoin par sac à dos
  exact numpy (8 tables, 2 s) ; stabilisation par lissage des duaux (α 0,7) et sous-fenêtres (split 3).
- **Résultat** : mécanique validée (coûts réduits = `col_dual` HiGHS), mais LP très dégénérée : +2 pts par tour
  (668 285 → 668 294 en 5 tours, 12 k colonnes/tour). Stabilisée : la LP du master dépasse 300 s dès 500 k colonnes,
  duaux non optimaux, valeurs incohérentes (609 k-720 k). Sur le 2 (m7) : +0,6 par itération.
- **Diagnostic** : la valeur se loge dans les lignes GUB (un paquet par créneau) et non dans les datasets, dont les
  duaux valent 0 ; le pricing par créneau est inopérant. Il faudrait un pricing par modèle et une vraie
  stabilisation (boîtes/Wentges) : non fait faute de temps (§5).

### 3.9 Modèle par blocs — 10/10 12:05 (AWS)
Réalisation CP-SAT par blocs, 2 passes de 60 s, 3 offres effectives : 661 189 / 660 075 / 660 832. Jamais compétitif
(mêmes causes que §3.4). Coût : ~6 cœurs AWS pendant 2 h.

### 3.10 Finitions instances 3 et 4 (`src/fin_*.py`) — 10/10 12:25 → 15:45, 2 cœurs
- **Inst 3** : MIP des rôles optimal en 30 s = borne → optimum prouvé (§3.3).
- **Inst 4** : observation clé : passer un modèle de f à h (ou l'inverse) ne change ni l'énergie ni la consommation
  totale, seulement la consommation de données **libres**. À ensemble de modèles fixé, le choix des tarifs est un sac
  à dos 4-D sur les données libres (`fin_fh4.py`, HiGHS optimal 76 s : +1 → 1 031 936). Puis MIP HiGHS du cœur
  |coût réduit LP| ≤ 12 (1 735 modèles, `fin_alt4.py --steps c --q 99999 --sub-time 2400`) : +1 → 1 031 937, réalisé
  à gaspillage 0 par `lns.py 4 --init lp --roles ... --exact 100000`. Deux tours de plus (2 × 2 400 s) : rien.
  Écart LP restant 10,98 = coûts réduits 9,5 + marges 2,4 (`fin_gap.py`). `fin_lns4.py` (sous-MIP q = 10..600) :
  0 mouvement accepté en 100 k itérations ; CP-SAT 2 workers : rien.
- **Inst 2/5/7** : `fin_fh.py` (tarifs optimaux à U fixé) montre +6 / +109 / +26 au niveau des rôles à consommation
  libre constante, mais l'application (`fin_switch.py`, 45 essais) est toujours < best : l'excès est piégé par petits
  morceaux (7 u./créneau sur le 5) dans des milliers de créneaux. `fin_rematch.py` (paquets aussi pour les fenêtres
  des candidats hors solution, 556 k colonnes) : optimal = 272 299 = borne de ses paquets. `fin_pack.py` (CP-SAT par
  blocs) : ne prouve rien sur 17 datasets × 27 créneaux en 20 s.
- **Diagnostic** : sur 2, 5, 7 c'est le **regroupement des datasets en paquets** qui bloque, pas les rôles.

### 3.11 Trois méthodes « gaspillage » sur le 6, orchestrées (10/10 16:10 → 18:10, départ commun 668 711)
#### m1 offre effective (`effective_loop.sh`) : abandonnée (§3.6).
#### m2 paquets exacts 1-3 datasets + set-partitioning par type (`src/m2_pack.py`, `m2_loop.sh`, `m2_night.sh`)
- **Idée** : à rôles fixés, colonnes = (créneau, sous-ensemble de 1-3 datasets) avec somme ∈ [lb, lb + δ] (K colonnes
  les plus serrées par créneau) + paquet courant et variantes ; chaque créneau exactement une colonne, dataset ≤ 1 ;
  min Σ consommation = max de datasets entiers libérés. Mode par blocs de B créneaux (LP instantanée, monotone).
- **Résultat** : 668 874 en isolé (+97-100/h, −10 k u. en 4 min sur une solution lâche), mais **0 sauvegarde** sur
  best/ : marge LP 0,03 % sur une solution déjà polie. Gardée en diversification (2 boucles la nuit).
#### m3 tabou sur l'affectation des datasets à rôles fixés, Rust (`src/m3_tabu/src/main.rs`, `m3_prep.py`, `m3_loop.sh`, `m3_launch.sh`)
- **Idée** : objectif = consommation pondérée (prix duaux LP) − λ·Σ e_s² (concentrer l'excès sur peu de créneaux pour
  libérer des datasets entiers). Mouvements : retrait vers le pool, déplacement, insertion, échange, **échange puis
  retrait**, cycle à 3 + retrait. 708 lignes de Rust, 85-170 k itérations/s. Boucle : tabou 60-180 s → `lns.py
  --start` 120-600 s (convertit les datasets libérés en valeur) → rematch.
- **Paramètres** : tenure, λ, ncand, stagnation, perturbation ; mu/kmax du LNS ; graine.
- **Gain** : 668 711 → **669 056 en 2 h** (+280 la 1re heure, +32 la 2e ; 18 cœurs AWS + 2 VM), gaspillage 207 477 →
  171 028 u. (0,827 % → 0,682 %). Nuit (42 boucles AWS + 10 VM) : +81 en 11 h → 669 137 ; ensuite +13 (669 156).
- **Diagnostic** : la tabou libère ~30 k u. en 2 min sur une solution lâche, puis plus rien une fois la solution polie
  (1 517 créneaux mono-dataset, excès concentré sur 275 créneaux ; seul le mouvement « déplacement » s'applique
  encore). Les 24 solutions de nuit à 669 137 ont les mêmes rôles et le même gaspillage sur 3 types / 4 : **plateau
  dégénéré**. Meilleure méthode du concours en gain/heure (voir §4).
- **À refaire** : la lancer dès le 10/10 matin au lieu du rematch seul ; ajouter dès le départ un objectif orienté
  « bascule h→f » (libérer des datasets libres de la bonne taille) plutôt que la consommation brute.

### 3.12 m4 CP-SAT ciblé sur les créneaux à fort excès (`src/m4_cp.py`, `m4_chain.py`, `m4_loop.sh`) — 10/10 18:27 → 20:23
Sous-problème par type : H = créneaux à excès ≥ 200 (blocs de 60-70) + 300 partenaires + ~520 datasets libres,
x[d, s], min consommation pondérée, hint = courant. 110 k variables, 7 cœurs AWS, 12 + 7 tours : toujours FEASIBLE
sans gain, **0 unité libérée**. Abandonné à 20:30.

### 3.13 m5 fenêtres sur mesure (`src/m5_windows.py`, `m5_loop.sh`) — même créneau
Remplacer l'occupant d'un créneau à fort excès par un modèle libre dont la fenêtre contient un sous-paquet du paquet
en place (0-2 datasets retirés), choix couplé par petit MIP highspy (énergie, Δvaleur, prix duaux). **0 remplacement**
sur best/. Abandonné à 20:30.

### 3.14 m7 : modèle exact au niveau des datasets, instance 2 (`src/m7_*.py`, `notes/M7.md`) — 11/10 07:10 → 09:20, 12 cœurs VM
- **Constat** : 100 % des données libres utilisées, gaspillage libre 14 412 u. ≈ 77 pts ; la seule difficulté est
  l'empaquetage des datasets libres dans les 1 150 créneaux plein tarif.
- **Modèles** : set-partitioning + rôles (`m7_cg.py`, `m7_cp.py`) avec pricing par DP de sac à dos (860 items × 115 k
  sommes, 0,3 s par type) ; maître entier sur un pool de 181 746 colonnes tirées au hasard : HiGHS 6 threads prouve en
  718 s que **272 299 est l'optimum du pool** ; CP-SAT 1 500 s : rien, borne 284 k. Réalisation exacte par type depuis
  rôles réduits (`m7_realize.py`, `m7_pack_cp.py`, 200 k binaires/type) : 271 678 à **272 138**, toujours 1 créneau non
  réalisé par type (≈ −250 chacun).
- **Apport** : borne valide **272 396** (MIP rôles entier, `m7_bound.py`) ; borne conditionnelle 272 320 si gaspillage
  ≥ niveau de best → 272 322 exige à la fois moins de gaspillage (< 13 000 u.) et un meilleur choix de modèles.
- **Diagnostic** : CG inopérante (duaux dégénérés, §3.8) ; les solveurs exacts ne descendent pas sous le gaspillage de
  best en < 25 min. Verdict : ne plus investir en exact sur le 2.

### 3.15 m6 : algorithme mémétique, instance 6 (`src/m6_*.py`, `m6_launch.sh`, `notes/M6.md`) — 11/10 07:30 → 12:00, 23 cœurs AWS
- **Idée** : population de solutions (`m6_pool.py`, verrou fcntl, distance = paquets non partagés, dmin 1 000) ;
  croisement A × B par **chaînes d'éjection** (`m6_cross.py`, `--mix p`) : rôles et score de A conservés, paquets de B
  importés créneau par créneau, les créneaux spoliés reprennent leur paquet de B ou un sous-ensemble exact du pool
  libéré (chaîne ≤ 4) ; puis tabou m3 → LNS → rematch → `save_if_better`.
- **Résultat** : 280 enfants ; score enfant = A dans 100 % des cas ; la tabou réduit le gaspillage dans 83 % des cas
  (contre 15 % depuis une solution polie) ; gaspillage population 163 361 → 161 643 u. **+6 direct (669 143)** : bascule
  modèle 5343 demi → plein (+16) et 1440 plein → demi (−10), énergie inchangée ; +13 via une boucle m3 repartie de
  l'enfant (669 156). Échecs : MIP de recombinaison A ∪ B (rend A), rematch sur toute la population (496 k colonnes,
  LP racine > 1 500 s).
- **Diagnostic** : **l'énergie est saturée** (reste 1,96e8 sur 9,98e14) : ajouter un modèle est impossible, seules les
  bascules h→f et les échanges de modèles peuvent gagner ; les 1-2 datasets libérés par la tabou (1 148-1 377 u.)
  n'y suffisent pas. 6 points en 1 h pour 23 cœurs.

### 3.16 m8 : bascules h→f ciblées et set-partitioning population (`src/m8_*.py`, `notes/M8.md`) — 11/10 09:30 → 18:00, 12 cœurs VM
- **Analyse** (`m8_analyse.py`) : sur best/6, 3 556 modèles utilisés (f 985, cibles z 1 249, **hc 2**, y 1 320),
  4 999/5 000 datasets utilisés. Une bascule n'existe que sous deux formes : hc→f (2 candidats, +15 et +14, besoin de
  datasets libres **inutilisés** de tailles précises) ou z→f (retirer un générateur : besoin ≥ 27 827 u. d'un type,
  alors que le gaspillage libre d'un type est 17-23 k u. éparpillé à 47 u./créneau : jamais rentable). Plafond
  réaliste +29.
- **Résultats** : scan de 516 solutions : 45 admettent une bascule (+4 à +8) mais max 669 143 < best. Tabou restreinte
  à un type (`m8_tabu.py`, 360 k it/s, 18 runs λ × mu) : 0 dataset libéré. Set-partitioning par type sur les paquets
  observés dans la population (`m8_popmip.py` HiGHS / `m8_popcp.py` CP-SAT, 32-44 k colonnes/type) : marge LP 3 848-
  5 120 u./type (de l'ordre des besoins), **aucun entier meilleur** (HiGHS 240-900 s, CP-SAT 600 s FEASIBLE/UNKNOWN).
  3 boucles jusqu'à 18:00 : 0 gain à 14:00.

### 3.17 m9 : colonnes exactes à rôles libres (`src/m9_mip.py`, `m9_loop.sh`, `notes/M9.md`) — 11/10 09:45 → 13:15, 14 cœurs AWS
- **Idée** : première formulation qui ne fixe pas les rôles : colonnes « paquet exact (1-3 datasets, numba `_enum3`)
  → besoin » pour 3 000-4 000 modèles candidats (coût réduit ≥ −θ) + 1 500-1 700 générateurs candidats ; MIP HiGHS
  global (rôles + paquets, énergie, générateurs ≥ cibles, f + h + y ≤ 1), hint = best/.
- **Résultat clé** : borne LP de cette famille **669 688-669 830** selon k/θ (157 k-713 k colonnes, IPM 2-6 min), à
  comparer à la LP des rôles 670 948 : **~1 100 pts de l'écart à la LP viennent de la granularité des paquets**, et le
  n°1 (669 777) est quasiment à la borne LP de la famille. `--fix-gen` : 669 583. Simplex dual racine 572 s (173 k
  colonnes) ; B&B : 77 MIP de 2 000 s, **0 amélioration**.
- **Diagnostic** : HiGHS n'utilise pas l'IPM dans son MIP ; au-delà de 200 k colonnes il ne reste plus de temps de B&B.

### 3.18 m9 RINS : plongeon LP, HiGHS puis CP-SAT (`src/m9_rins*.py`, `notes/M9_RINS.md`) — 11/10 12:30 → 13:50, 22 cœurs AWS
- **Idée** : fixer les colonnes sur lesquelles la LP (IPM, cache npz) et best/ s'accordent, MIP réduit exact en
  tranches courtes (cycle de seuils 0,9/0,7/0,5, frac, eps0, coupure objectif ≥ courant + 1).
- **Constat** : la LP IPM est quasi entière sur les rôles (9 fractionnaires / 4 849) mais très fractionnaire sur les
  paquets (206 colonnes de best/ à ≥ 0,999, 516 à ≥ 0,5 sur 1 677). MIP réduit après presolve 3 779 × 5 784, racine
  12 s, même borne que la LP complète.
- **Résultats** : voisinages « colonnes de best/ ≥ 0,5 fixées » **prouvés sans amélioration** en 5-157 s ; voisinages
  de 8-17 k colonnes libres : limite de temps à 300-1 800 s (0-1 289 nœuds), aucune solution améliorante. CP-SAT
  (8 workers, 900 s) : UNKNOWN avec coupure (borne 674-678 k, relaxation bien plus lâche que la LP), = hint sans
  coupure. **AWS arrêté à 13:50**.
- **Diagnostic** : l'écart d'intégrité est dans l'empaquetage (set packing dégénéré) ; toute amélioration exige de
  défaire des paquets que la LP ne soutient qu'à 0,5-0,9.

### 3.19 m10 : CP-SAT global rôles + datasets (`src/m10_cp.py`, `m10_launch.sh`, `notes/M10.md`) — 11/10 09:40 → 12:30, 16 cœurs AWS
- **Idée** : un seul modèle exact (rôles f/h/y/z, x[d, créneau], énergie, fenêtres, copyright, comptage générateurs),
  objectif = score exact (vérifié : hint décodé = 669 156), réduit en fixant les rôles communs aux 12 meilleures
  solutions du pool m6 + liberté par coût réduit LP (`--lpk --targets --worst`), `--type t` pour un modèle par type.
- **Tailles** : 266 k variables (98 modèles libres, 8 workers) ; 392-402 k par type (2 workers chacun) ; RAM 1-7 Go.
- **Résultat** : 7 tours × 1 200 s, **0 gain**, borne CP-SAT +9 000-15 000 (inutile). Les LNS internes de CP-SAT
  tournent (0,6-0,8 s/voisinage) sans rien trouver. Le pool a des rôles identiques à 2 modèles près : la fixation par
  le pool ne libère rien.
- **Diagnostic** : même mur que m4/m7 (symétrie de x[d, s]) ; énergie saturée → toute insertion exige retrait +
  ré-empaquetage global. Variante non essayée : fixer aussi les x des créneaux fixés (~50 k variables).

---

## 4. Enseignements transversaux

### 4.1 Décomposition rôles / empaquetage
- Le problème se décompose naturellement en (i) choix des rôles (sac à dos multi-ressources sur énergie, données libres
  et totales par type, générateurs) et (ii) empaquetage des datasets dans les créneaux (subset-sum / set-partitioning).
  La LP des rôles donne en 1 s une borne à 0,01-0,27 % des scores finaux et des duaux utilisables comme prix.
- La décomposition est **exacte quand une ressource est lâche** (inst 3 : données à 49 % → optimum prouvé ; inst 4 :
  gaspillage 0 atteignable → 10 pts de la borne) et **trompeuse quand l'offre de données est saturée** (2, 5, 6, 7) :
  les rôles optimaux sont déjà atteints, tout l'écart est dans le gaspillage d'empaquetage (inst 6 : rôles idéaux au
  gaspillage courant = 668 711 contre LP 670 948 ; LP à colonnes exactes 1-3 datasets ≈ 669 790).
- Observation f↔h : changer le tarif ne change ni l'énergie ni la consommation totale → sac à dos 4-D sur les données
  libres à modèles fixés (`fin_fh*.py`). Rentable seulement quand l'excès récupéré est en datasets **entiers**.

### 4.2 Énergie saturée et gaspillage
- Sur le 6, énergie à 99,99998 % et 4 999/5 000 datasets utilisés : la solution ne peut plus gagner que par bascules
  h→f (2 candidats, +29 max) ou échanges de modèles exigeant un ré-empaquetage global. Le gaspillage (0,68 %) est
  éparpillé (47 u./créneau libre), donc inutilisable sans tout défaire.
- Le gaspillage a été le fil conducteur : 2,0 % (LNS brut) → 1,3 % (mu·gaspillage) → 0,83 % (rematch ↔ LNS) → 0,68 %
  (tabou m3) → 0,65 % (m6). Chaque palier a demandé une méthode différente et chaque méthode s'est éteinte en
  quelques heures.

### 4.3 Plateau dégénéré
- 24 solutions de nuit à 669 137, distantes de 2 400-3 000 paquets entre elles, avec les mêmes rôles et le même
  gaspillage sur 3 types / 4 : des milliers de solutions équivalentes, aucune meilleure. Les méthodes « diversité »
  (élite, relinking, mémétique) recombinent des points du même plateau. Un vrai saut exige un autre jeu de rôles,
  mais les autres bassins partent 1 400-8 000 pts plus bas (§3.6).

### 4.4 Limites des solveurs
- **HiGHS 1.15.1** : segfault au-delà de ~1 M colonnes (presolve) ; simplex dual très lent sur les LP dégénérées
  (572 s pour 173 k colonnes, > 1 000 s pour 295 k) alors que l'IPM est 3-5× plus rapide mais inutilisable dans le MIP ;
  `scipy.milp` sans hint est inutilisable (aucune solution entière en 15 min), highspy + hint indispensable ; threads non
  réglables via scipy (épingler avec `taskset`).
- **CP-SAT** : la formulation x[dataset, créneau] est trop symétrique : ne prouve rien sur 17 × 27 en 20 s, ne gagne
  rien sur 110 k-400 k variables en 20 min × 8 workers, bornes 10-15 k au-dessus de la LP. Utile uniquement avec hint
  complet et petit voisinage, et encore (m9 RINS : UNKNOWN).
- **highspy et ortools ne s'importent pas dans le même processus** (conflit de symboles) : LP via `scipy.optimize.linprog`
  dans les scripts CP-SAT, ou sous-processus (`m9_rins_cp_solve.py`).
- Bug du scoreur : `modelMappings` sans contrôle de bornes (indice négatif accepté) ; `save_if_better.py` refuse tout
  indice hors [0, n). Non exploité.

### 4.5 Organisation
- `src/save_if_better.py` (scoreur officiel + verrou fcntl + `best/scores.json` + commit) a tenu 399 améliorations
  sans jamais perdre ni corrompre une solution, avec jusqu'à 60 processus écrivant depuis deux machines.
- `cloud_sync.sh` (3 min) : rapatrie best/ d'AWS → save_if_better local, pousse le best local → validé là-bas. Machine
  AWS 48 vCPU du 10/10 12:05 au 11/10 13:50 (~26 h, charge ≈ 48-52).
- Boucles `setsid nohup ... --until "<fin UTC>"` avec arrêt programmé ; piège : un `pkill -f` dont le motif apparaît
  dans le shell appelant tue ce shell (ancrer avec `^`). Un core dump HiGHS a occupé 1 cœur 3 h 50 avant d'être vu.
- Sous-agents parallèles (m6/m7, m8/m9/m10) avec notes dédiées `notes/M*.md` ; limite de session interrompant les
  agents à 09:55 le 11/10, les calculs autonomes ont continué (boucles shell + save_if_better).
- Bugs coûteux : `_pick_gen` (4 essais) a bridé le LNS toute la première nuit ; nom de fichier 0,0171 ≠ 0,01710 ;
  chaînes m6 absorbant le dataset libre ; course entre workers m6.

### 4.6 Rendement par heure de calcul (instance 6, ordre de grandeur)
| méthode | période | cœurs | gain | gain/h·cœur |
|---|---|---|---|---|
| glouton + init LP + LNS | 09/10 18:24-19:08 | 1-2 | 611 810 → 663 760 (+52 k) | ≈ +35 000 |
| 12 LNS parallèles | 09/10 19:08-20:04 | 12 | +3 342 | ≈ +300 |
| LNS nuit | 09/10 20:07 → 10/10 07:00 | 12 | +588 | ≈ +4,5 |
| rematch ↔ LNS | 10/10 07:30-16:00 | 10 → 48 | +976 | ≈ +3 |
| **tabou m3 → LNS → rematch** | 10/10 16:10-18:10 | 20 | +345 | ≈ +8,6 |
| m3 nuit | 10/10 18:30 → 11/10 07:00 | 52 | +81 | ≈ +0,12 |
| m6 mémétique | 11/10 07:30-12:00 | 23 | +19 | ≈ +0,2 |
| m4, m5, m7, m8, m9, m9 RINS, m10 | 10/10 18:27 → 11/10 13:50 | 7-22 chacune | 0 | 0 |
Les méthodes exactes de la dernière journée (≈ 400 cœurs·h cumulés) n'ont rien rapporté, mais ont fourni le diagnostic
(borne de famille 669 690-669 830, voisinages prouvés vides) qui explique le plateau.

---

## 5. Pistes non explorées (par ordre d'intérêt estimé)
1. **Ré-empaquetage global par type avec colonnes serrées** (JOURNAL « Finitions ») : pour tous les créneaux plein
   tarif d'un type à la fois, générer par subset-sum des colonnes de somme ∈ [lb, lb + δ], δ ≈ 0-5 (bien plus serrées que
   `rematch --gen` qui échantillonne dans [lb, lb + 60]), puis set-partitioning HiGHS maximisant le nombre de créneaux
   exacts ; ensuite h→f avec `fin_fh.py --keep-use`. m2 et m8_popmip s'en approchent mais avec des colonnes observées ou
   δ adaptatif, et la marge LP (0,03 % / 4-5 k u. par type) n'a jamais été convertie en entier.
2. **Génération de colonnes avec pricing par modèle et stabilisation duale** (M7 §4, JOURNAL 09:00) : pricing = somme
   des meilleures colonnes de tous les créneaux d'un modèle, duaux stabilisés (boîtes, lissage de Wentges ou du Pessoa)
   pour sortir de la dégénérescence ; master réduit (< 200 k colonnes) pour que la LP reste < 60 s.
3. **Tabou m3 orientée bascule h→f** (M6 verdict) : pondérer la libération des datasets libres des types/tailles
   nécessaires aux 2 candidats hc→f (poids `w_free` dans `m3_prep.py`), objectif « somme libre libérée ≥ copyright à
   remplacer ».
4. **m10 réduit** (M10) : fixer aussi les x des créneaux fixés (~50 k variables) pour laisser CP-SAT prouver l'optimum
   d'un voisinage ; mode `--type` à 8 workers avec `--small 1500`.
5. **MIP du cœur de l'instance 4 avec plus de threads / sur le cloud** (cible coûts réduits ≤ 5, écart 10 à la LP).
6. **LNS en Rust** : la boucle Python plafonne à ~1 it/s sur le 7 et ~10 it/s sur le 6 ; un LNS natif avec évaluation
   incrémentale aurait multiplié par 50-100 le nombre de voisinages visités sur 2, 5, 7 (plateaux à −23 / −167 / −77).
7. **Autres bassins de rôles sur le 6 avec réalisation tabou** : les bassins de §3.6 ont été réalisés en glouton
   (1,7 % de gaspillage) avant l'existence de m3 ; une réalisation tabou + rematch pourrait les rendre compétitifs.
8. Données **non mesurées** : sensibilité de m3 à λ/tenure (balayage m8 partiel seulement), effet d'un `--kmax` > 40 sur
   le LNS, intérêt du recuit sur les instances 5 et 7 (testé seulement sur le 6).

---

## Annexe — fichiers principaux (`src/`, 51 scripts Python, 28 scripts shell, 1 binaire Rust)
| étape | fichiers |
|---|---|
| infrastructure | `save_if_better.py`, `run_starter.py`, `inspect_sol.py`, `waste.py`, `waste_split.py`, `status.sh`, `cloud_sync.sh`, `night.sh`, `run.sh`, `relance_*.sh` |
| glouton / LP / LNS | `greedy.py`, `lp_bound.py`, `lns.py`, `loop_lns.sh`, `elite.py` (relinking), `basin.sh`, `basin2.sh`, `effective_loop.sh` |
| rematch | `rematch.py`, `loop_rematch.sh`, `loop_rematch_big.sh`, `iterate.sh`, `diag_roles.py` |
| CP-SAT premiers essais | `cpsat_repair.py`, `cp_pack.py`, `realize_cp.py` |
| finitions 2-5, 7 | `fin_realize.py`, `fin_fh.py`, `fin_fh4.py`, `fin_alt4.py`, `fin_mip4.py`, `fin_gap.py`, `fin_lns4.py`, `fin_cp4.py`, `fin_pack.py`, `fin_rematch.py`, `fin_switch.py` |
| m2 / m3 / m4 / m5 | `m2_pack.py`, `m2_loop*.sh`, `m2_night.sh` ; `m3_tabu/src/main.rs`, `m3_prep.py`, `m3_loop.sh`, `m3_launch.sh` ; `m4_cp.py`, `m4_chain.py`, `m4_loop.sh` ; `m5_windows.py`, `m5_loop.sh` |
| m6 → m10 | `m6_common.py`, `m6_pool.py`, `m6_cross.py`, `m6_worker.py`, `m6_stats.py`, `m6_launch.sh` ; `m7_roles.py`, `m7_bound.py`, `m7_cg.py`, `m7_cp.py`, `m7_realize.py`, `m7_pack_cp.py` ; `m8_analyse.py`, `m8_apply.py`, `m8_tabu.py`, `m8_popmip.py`, `m8_popcp.py`, `m8_scan.sh`, `m8_loop.sh` ; `m9_mip.py`, `m9_loop.sh`, `m9_rins.py`, `m9_rins_loop.sh`, `m9_rins_cp.py`, `m9_rins_cp_solve.py`, `m9_rins_cp_loop.sh` ; `m10_cp.py`, `m10_launch.sh` |
