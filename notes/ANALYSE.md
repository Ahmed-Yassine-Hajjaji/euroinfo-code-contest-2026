# ANALYSE — IA responsables (Euro-Information 2026)

## Le problème en une phrase
Choisir des modèles à entraîner (sac à dos sur l'énergie) et leur affecter des datasets (chaque dataset à un seul
modèle) pour que, pour chaque type de données requis, la somme des tailles tombe dans [lowerBound, upperBound],
en maximisant la somme des valeurs. Un modèle mono-besoin peut servir de « générateur » pour couvrir entièrement
un besoin d'un autre modèle.

## Objectif : MAXIMISER
Score = Σ valeur des modèles entraînés (hors générateurs).
- Modèle avec au moins un dataset copyrighté → valeur // 2.
- Modèle cible d'un générateur → valeur // 2.
- Les deux malus NE SE CUMULENT PAS (c'est un seul flag `defiled`).
- Générateur : valeur 0, mais son énergie compte.
Classement Isograd : la formule de l'énoncé (meilleur/joueur) est écrite comme pour un coût ; en pratique on
maximise la valeur, chaque instance vaut au plus 1 000 000 points, et 1 % de valeur ≈ 10 000 points partout.

## Ce que fait EXACTEMENT test_solution.py (la référence)
- Format : `{"dataMappings": [[dataset, modèle], ...], "modelMappings": [[source, cible], ...]}`, entiers Python.
- `model_used` = tous les modèles présents dans dataMappings ET modelMappings (sources et cibles).
- Chaque dataset au plus une fois ; son type doit être dans les besoins du modèle.
- Source : doit avoir exactement 1 besoin, être utilisée une seule fois comme source, et son besoin doit être
  satisfait PAR DES DATASETS (rempli au moment du test). Sa valeur n'est pas comptée, son énergie oui.
- Cible : le besoin du type de la source est marqué « satisfait » (-1) quelle que soit la quantité, puis flag defiled.
  → Les datasets de ce type éventuellement donnés à la cible sont gaspillés (autorisé mais inutile).
- Tous les autres besoins de chaque modèle utilisé (non source) : lb ≤ somme ≤ ub, sinon solution invalide.
- Énergie totale (sources + modèles entraînés) ≤ energyCap.
- Si un seul point est violé → score 0 pour le fichier. Toujours valider avant de soumettre.
- ⚠️ (vérifié) `modelMappings` n'a AUCUN contrôle de bornes : un indice ≥ nb modèles fait planter le scoreur
  (IndexError), un indice négatif est accepté et aliasé par Python (`models[-1]` = dernier modèle).
  On ne s'en sert pas (exploit d'un bug, le correcteur officiel peut différer) : `save_if_better.py` refuse
  tout indice hors [0, n).
- Un modèle « cible » d'un générateur ne peut pas ensuite servir de source pour ce type (son remplissage vaut -1 < lb).
- `lowerBound` ≥ 1 partout (vérifié) : aucun modèle n'est « gratuit » sans données.

## Conséquences stratégiques (les vraies astuces)
1. **Un modèle est soit « plein tarif », soit « demi-tarif ».**
   - Plein tarif : uniquement des datasets libres, aucun générateur.
   - Demi-tarif : une fois dévalué, utiliser des datasets copyrightés ET des générateurs ne coûte plus rien en valeur.
   → Réserver les datasets libres aux modèles plein tarif ; donner le copyrighté aux modèles demi-tarif.
2. **Un générateur ignore le copyright** (sa valeur n'est pas comptée) → le nourrir avec des datasets copyrightés.
3. **Levier énorme des générateurs** : un mono-modèle avec lb minuscule (min = 1, 10e percentile ≈ 4 000-9 000)
   consomme très peu de données mais couvre un besoin cible de ~18 000-50 000. Coût : son énergie.
4. **Besoins « impossibles » (ub < lb)** : présents dans toutes les instances sauf la 1 (58 à 1 043 modèles). Ces
   besoins ne peuvent être couverts QUE par un générateur → ces modèles ne sont pas morts, ils exigent un générateur.
   EXCEPTIONS : instance 4 (aucun mono-modèle) → ses 380 modèles impossibles sont réellement morts ; un mono-modèle
   impossible ne peut pas servir de générateur (son propre besoin doit être rempli par des datasets).
5. **Gaspillage de données** : viser une somme juste au-dessus de lb (et ≤ ub). Les petits datasets servent de
   « pièces d'appoint » pour atteindre des fenêtres étroites.
6. Une cible peut avoir TOUS ses besoins couverts par des générateurs (un par type) → zéro dataset direct.

## Statistiques des instances (datasets du starter kit = fichiers Isograd, vérifié identiques)
| # | nom | modèles | datasets | cap/énergie totale | offre/demande données | copyright | remarque |
|---|-----|---------|----------|--------------------|-----------------------|-----------|----------|
| 1 | example | 5 | 5 | 0,61 | 0,55 | 60 % | **optimum = 12 946** (recherche exhaustive) |
| 2 | medium | 3 000 | 10 000 | 0,137 | ~0,35 | 66 % | énergie et données toutes deux limitantes |
| 3 | free | 5 000 | 20 000 | 0,126 | ~0,42 | 0 % | aucun copyright : seul malus = générateur |
| 4 | precise | 8 000 | 40 000 | 0,168 | ~0,50 | 50 % | AUCUN mono-modèle → pas de générateurs ; intervalles très étroits (1 102 avec lb = ub) ; 380 modèles impossibles |
| 5 | energy | 11 000 | 100 000 | **1,087** | ~0,96 | 66 % | énergie NON limitante → tout est question de données |
| 6 | shortage | 15 000 | 5 000 | 0,132 | **~0,04** | 41 % | pénurie extrême : générateurs indispensables ; mono-modèles peu chers en valeur (méd. 299) vs multi (méd. 750) |
| 7 | big | 50 000 | 250 000 | 0,172 | ~0,53 | 66 % | grande taille : algos en O(n log n), Rust conseillé |

Valeurs 0-1000 (méd. ~500), énergies 1 à ~1,25e12 (méd. ~5e11), pas de corrélation visible valeur/énergie
→ le ratio valeur/énergie varie énormément : les modèles à faible énergie sont de l'or.
Tailles des datasets 1-10 000 (méd. ~5 000), lb médian ~18 000 → ~3-4 datasets par besoin.
Note : instance 4 « precise » a une largeur relative d'intervalle médiane ≈ 0 → il faut un sous-ensemble dont la
somme tombe dans une fenêtre minuscule (subset-sum) : algo de remplissage soigné obligatoire.

## Plan d'algorithme
### A. Constructif glouton (base)
- Priorité d'un modèle = valeur_effective / (α · énergie/energyCap + Σ_types β_t · lb_t / offre_t).
  α, β = « prix » des ressources (style relaxation lagrangienne) ; les tirer aléatoirement / les régler par instance.
  (« Omettre certains paramètres » : instance 5 → α = 0 ; instance 6 → β très élevé ; instance 3 → copyright ignoré.)
- Pour chaque modèle, deux options évaluées : plein tarif (datasets libres seuls) ou demi-tarif (copyrightés +
  libres + générateurs). Prendre la meilleure selon la priorité.
- Remplissage d'un besoin : choisir des datasets du bon type dont la somme ∈ [lb, ub] avec un excès minimal
  (gros d'abord puis appoint par petits ; ou mini-DP / recherche bornée sur les candidats triés ; indexer les
  datasets libres par type dans des structures triées, ex. SortedList / BTreeMap).
- Générateurs : pour un besoin coûteux en données, comparer « datasets » vs « meilleur générateur disponible »
  (énergie faible, lb faible, même type, non encore utilisé).

### B. Amélioration
- LNS : retirer k modèles (aléatoires, ou ceux au pire ratio, ou un type de données donné), libérer datasets,
  énergie et générateurs, reconstruire en glouton avec priorités bruitées ; accepter si meilleur (ou recuit simulé).
- Mouvements simples : échange d'un modèle choisi contre un non choisi ; ajout d'un modèle dans l'énergie restante ;
  passer un modèle demi-tarif en plein tarif si des datasets libres se libèrent ; échanger des datasets entre
  deux modèles pour réduire l'excès.
- Repartir toujours de la meilleure solution connue ; graines multiples en parallèle (14 cœurs).

### C. Borne supérieure (pour savoir où on en est)
Relaxation LP (HiGHS) : variables x_m ∈ [0,1], contraintes énergie + offre de données par type (en ignorant
l'appariement exact) → borne optimiste. Sert à mesurer l'écart restant par instance.

## Instance 1
Optimum = 12 946 (prouvé par énumération). Deux solutions optimales (vérifiées avec le scoreur) :
- solution d'exemple fournie : `{"dataMappings": [[0,3],[1,1],[2,1],[4,4]], "modelMappings": [[3,1]]}` (générateur = modèle 3) ;
- variante : `{"dataMappings": [[0,0],[1,1],[2,1],[4,4]], "modelMappings": [[0,1]]}` (générateur = modèle 0).
(Corrigé : l'analyse initiale disait à tort que la 2ᵉ était la solution d'exemple.)
