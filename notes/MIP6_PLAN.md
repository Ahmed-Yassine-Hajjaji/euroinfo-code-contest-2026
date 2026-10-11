# MIP6_PLAN — Modèle exact « créneaux ↔ datasets » pour l'instance 6 (conception, 2026-10-09 soir)

Document de conception uniquement : rien n'a été lancé ni modifié ce soir (les 14 cœurs sont pris par la nuit).
Les chiffres cités viennent d'une lecture (quelques secondes, mono-thread) de `datasets/instance_6.json`,
`best/instance_6.json`, `runs/lp_6.json` et `runs/mipr_6.json`.

Situation : 667 214 (best/) contre 669 632 (n°1) et 670 948 (borne LP agrégée), 670 611 (MIP agrégé réduit).
Il manque 2 418 points sur le n°1, soit 0,36 % ; la LP n'est qu'à 0,2 % au-dessus du n°1.

---

## 0. Constat préalable : où est vraiment le levier

### 0.1 L'appariement générateur → cible est DÉJÀ exact dans le MIP agrégé
Dans le scoreur, un générateur g (mono-besoin de type t_g) couvre entièrement le besoin t_g de sa cible, quelle que
soit la cible. Le coût d'un générateur (énergie e_g, données lb_g..ub_g pour son propre besoin) et l'effet sur la
cible (besoin marqué couvert, valeur // 2) ne dépendent pas du couple (g, m) choisi. Le graphe « générateurs de
type t ↔ besoins-cibles de type t » est donc biparti complet : par Hall, un appariement parfait existe dès que
`Σ_m z[m,t] ≤ Σ_{g : t_g = t} y_g`, ce que `lp_bound.py` impose déjà (lignes R_G). Les règles restantes sont
couvertes par les rôles : f + h + y ≤ 1 (une cible, h = 1, n'est pas source ; une source, y = 1, n'est pas cible),
z ≤ h, z = h si lb > ub. Conclusion : **ajouter des variables x[g,m] n'apporte rien au score** ; l'appariement
se reconstruit après coup par n'importe quel couplage par type (cf. §2.4 pour la variante explicite, si on y tient).

### 0.2 Pourquoi la réalisation des rôles a échoué (hypothèse à confirmer en 10 s demain matin)
Rôles LP/MIP de l'instance 6 : F = 992 modèles (1 697 créneaux de données, libres seulement), H = 1 248 modèles
(tous cibles « tout-générateur », **0 créneau de données**), Y = 1 317 générateurs (1 317 créneaux).
- Σ lb des créneaux F = 14,83 M pour 14,85 M de données libres (99,8 %) ; Σ lb des créneaux Y = 10,23 M pour les
  10,26 M restants. Énergie 99,985 %. **La LP suppose un gaspillage nul** sur 3 014 créneaux pour 5 000 datasets
  (1,5–1,7 dataset par créneau, fenêtres larges de ~2 200–3 800 pour des lb médians ~20 000).
- La réalisation séquentielle (`lns.py --init lp --roles`) place les F d'abord avec `Pools.fill` (glouton
  gros-d'abord + finisseur + paires ; l'exact ne se déclenche que si ≤ 300 candidats, or les pools libres en ont
  ~700 par type), puis les H via `_pick_gen` (4 essais, générateur nourri par `fill`). Chaque excès consomme la
  marge nulle → les derniers F et beaucoup de générateurs ne trouvent plus de combinaison → énergie 48 %.
- Ce n'est donc pas un problème d'appariement mais de **partition des datasets en créneaux** (multi-subset-sum
  à fenêtres). Prix dual LP des données ≈ 0,0052 pt / unité : le gaspillage actuel (1,3 % ≈ 326 k unités)
  vaut ≈ 1 700 pts, soit la moitié de l'écart à la LP ; le reste est l'intégralité des rôles (~340) et la
  non-réalisabilité des rôles LP. Le n°1 est forcément à ≲ 0,6 % de gaspillage.

**Décision de conception : le MIP6 est un modèle au niveau des datasets (agrégés en classes de taille), rôles et
créneaux ensemble, avec le couplage générateurs/cibles par comptage par type.** C'est ce qui manque réellement.

---

## 1. Données et notations (instance 6)
- Modèles M, |M| = 15 000 ; valeur v_m, énergie e_m ; besoins R_m = {(t, lb, ub)}, |R_m| ∈ {1,2,3,4}
  (6 018 mono, 4 736 bi, 2 181 tri, 2 065 quadri). Cap énergie C (= 13,2 % de Σ e_m). 10 % des modèles ont e_m = 1.
- Mono réalisables (générateurs possibles) G = {m : |R_m| = 1, lb ≤ ub} : 5 841 (177 mono impossibles).
  491 ont lb ≤ 5 000, ~300–600 ont lb = 1.
- Besoins impossibles (lb > ub) : 272 modèles ; un tel besoin ne peut être couvert que par un générateur.
- Datasets D, |D| = 5 000 : type t_d, taille s_d ∈ [2, 9 996] (≈ uniforme, ~1 250 par type), copyright c_d
  (41 % copyrightés). Offre par type ≈ 6,1–6,5 M (libre ≈ 3,6–3,8 M). Demande Σ lb ≈ 707 M → ratio 0,035.
- Créneau (slot) : un besoin (m, t) rempli par des datasets, ou le besoin propre d'un générateur g.
  Un créneau reçoit un ensemble de datasets de type t dont la somme ∈ [lb, ub] ; créneau d'un modèle plein tarif
  → datasets libres seulement.

## 2. Formulation de référence (complète, niveau dataset)

### 2.1 Variables
| var | domaine | sens |
|---|---|---|
| f_m | {0,1} | m entraîné plein tarif (interdit si un besoin est impossible) |
| h_m | {0,1} | m entraîné demi-tarif |
| y_g | {0,1}, g ∈ G | g utilisé comme générateur |
| z_{m,t} | {0,1}, (m,t) ∈ R_m | besoin t de m couvert par un générateur |
| a_{d,(m,t)} | {0,1}, t_d = t, s_d ≤ ub_{m,t}, lb ≤ ub | dataset d affecté au créneau (m,t) |
| a_{d,g} | {0,1}, t_d = t_g, s_d ≤ ub_g | dataset d affecté au créneau propre du générateur g |

Activation d'un créneau de données : act_{m,t} = f_m + h_m − z_{m,t} ∈ {0,1} ; act_g = y_g.

### 2.2 Contraintes
1. Rôles : f_m + h_m + y_m ≤ 1 (y_m seulement si m ∈ G).
2. Générateur ⇒ demi-tarif : z_{m,t} ≤ h_m ; besoin impossible : z_{m,t} = h_m (et f_m = 0).
3. Comptage générateurs/cibles par type : Σ_m z_{m,t} ≤ Σ_{g ∈ G, t_g = t} y_g pour t = n,t,i,c
   (égalité à l'optimum, un générateur sans cible ne sert à rien). C'est l'appariement (§0.1).
4. Énergie : Σ_m e_m (f_m + h_m) + Σ_g e_g y_g ≤ C.
5. Un dataset au plus une fois : Σ_{créneaux s compatibles} a_{d,s} ≤ 1.
6. Fenêtre du créneau : lb_s · act_s ≤ Σ_d s_d a_{d,s} ≤ ub_s · act_s (pour (m,t) et pour g).
7. Copyright : a_{d,(m,t)} ≤ h_m pour tout d copyrighté (un créneau plein tarif n'accepte que du libre) ;
   aucune contrainte pour les créneaux de générateurs (leur valeur n'est pas comptée).
8. (implicite) Un dataset n'est affecté qu'à un créneau actif : découle de 6 (act = 0 ⇒ somme ≤ 0 ⇒ a = 0).
9. (optionnel, redondant mais aide l'LP) nb de datasets par créneau ≤ ⌊ub/ s_min⌋ ; a_{d,s} ≤ act_s.

### 2.3 Objectif
max Σ_m v_m f_m + ⌊v_m/2⌋ h_m (exactement la formule du scoreur ; les générateurs valent 0).
Second critère (lexicographique, §4.4) : min Σ_{d,s} s_d a_{d,s} = données consommées (≡ min gaspillage à rôles
fixés, ≡ max de données libres laissées au LNS).

Validité : toute solution entière de 1–7 est acceptée par `test_solution.py` (chaque règle lue dans
notes/ANALYSE.md a sa contrainte ; les générateurs ont un unique besoin par définition de G ; une cible a h = 1
donc y = 0 → jamais source ; les index sont ceux de l'instance, 0-based).

### 2.4 Variante avec appariement explicite (pour mémoire)
x_{g,m} ∈ {0,1} pour t_g ∈ types(m), g ≠ m ; y_g = Σ_m x_{g,m} ; z_{m,t} = Σ_{g : t_g = t} x_{g,m}.
Taille : ~5 841 générateurs × ~7 500 besoins compatibles par type ≈ **44 M de variables** pour une information que
le comptage (contrainte 3) porte déjà exactement. À ne construire que si un coût dépendant du couple apparaissait
(il n'y en a aucun dans le scoreur). Reconstruction après coup : par type t, apparier dans n'importe quel ordre
les g avec y_g = 1 et les (m,t) avec z_{m,t} = 1 (listes de même longueur à l'optimum ; si Σ y > Σ z, retirer
les générateurs excédentaires, qui ne font que coûter de l'énergie).

### 2.5 Taille brute
- Rôles : 15 000 f + 15 000 h + 5 841 y + 30 293 z ≈ 66 k binaires (comme le MIP actuel, qui se résout vite).
- Affectation a : par type, ~1 250 datasets × (~7 500 créneaux de modèles + ~1 460 générateurs) ≈ 11 M → **~45 M
  binaires** au total. Hors de portée : il faut réduire (§3).

---

## 3. Réductions pour résoudre en temps raisonnable

### 3.1 Restreindre les modèles candidats au support LP + marge (÷ 4 sur les créneaux)
- La LP agrégée est quasi entière (15 variables fractionnaires sur 35 841). Support S₀ = {f ou h ou y > 1e-6}
  = 992 + 1 248 + 1 317 = 3 557 modèles, 3 014 créneaux.
- Marge : modèles hors support au meilleur coût réduit LP (coût réduit de f_m = v_m − π_E e_m − Σ_t (π_F,t + π_T,t) lb ;
  de h_m = ⌊v_m/2⌋ − π_E e_m − Σ_t min(π_T,t lb, π_G,t) ; de y_g = −π_E e_g − π_T lb_g + π_G,t). Garder les K ≈ 600–1 000
  meilleurs (seuil ≈ −30 pts, soit ~6 000 unités de données au prix dual). Ils permettent des échanges quand un
  modèle du support ne se réalise pas sans gaspillage.
- Les modèles du support gardent leurs deux rôles possibles (f et h, ou y) : on ne fixe pas, on restreint.
  Les 15 variables fractionnaires sont évidemment dans le support.
- Résultat : ~4 300 modèles, ~3 800 créneaux (1 700 F, ~100 H, 1 300 Y, ~700 de marge).

### 3.2 Agréger les datasets en classes de taille (÷ 12 sur les colonnes, et supprime la symétrie)
Datasets interchangeables à taille près : classe k = (type, copyright, intervalle de taille [s_lo(k), s_hi(k)]),
multiplicité N_k. Variable entière n_{k,s} ∈ {0..min(N_k, ⌊ub_s / s_lo(k)⌋)} = nombre de datasets de la classe k
dans le créneau s. La fenêtre devient **conservative** :
   Σ_k s_lo(k) n_{k,s} ≥ lb_s · act_s   et   Σ_k s_hi(k) n_{k,s} ≤ ub_s · act_s,
ce qui garantit que N'IMPORTE QUEL choix de datasets réels dans les classes respecte [lb, ub] (réalisation
toujours valide, §4.3). Perte : la fenêtre se rétrécit de Σ (largeur de classe) sur les datasets du créneau.
- Largeurs adaptatives (la « monnaie » doit être précise, les gros datasets non) : w = 50 pour s < 1 000
  (20 classes), w = 200 pour 1 000–4 000 (15), w = 500 pour 4 000–10 000 (12) → 47 intervalles × 2 copyright ≈
  **94 classes par type**, ~13 datasets par classe en moyenne.
- Perte maximale sur un créneau de 2–3 datasets : ~1 000–1 500 pour des fenêtres de 2 200–3 800 : acceptable ;
  pour un générateur à lb = 1 (1 dataset ≤ ub) : aucune perte. Si une fenêtre devient vide (ub' < lb'), le créneau
  n'est simplement pas réalisable à ce niveau : on s'en apercevra au nombre de tels créneaux (à logger ; si > 1 %
  des créneaux du support, resserrer w).
- Contrainte 5 devient : Σ_s n_{k,s} ≤ N_k ; contrainte 7 : pour un créneau F, seules les classes libres existent.
- Taille : créneaux F 1 700 × 47 classes libres ≈ 80 k ; générateurs 1 300 × (classes avec s_hi ≤ ub_g : de 15 à
  94, ~50 en moyenne) ≈ 65 k ; marge 700 × 70 ≈ 50 k ; → **≈ 200 k variables entières + ~10 k binaires de rôles**,
  ~4 000 contraintes de fenêtre, ~400 contraintes de classes, 1 d'énergie, 4 de comptage. Un MIP moyen ;
  l'LP relâchée est de type transport-avec-fenêtres (rapide ; quelques dizaines de secondes attendues).

### 3.3 Décomposer par type quand les rôles sont fixés (÷ 4 supplémentaire, 4 solveurs en parallèle)
À rôles fixés (f, h, y, z donnés), les 4 types sont indépendants : par type t, affecter les datasets de type t aux
créneaux de type t. Chaque sous-problème ≈ 950 créneaux × 94 classes ≈ **50 k entiers**, objectif min consommation
(gaspillage) ; ou, version « robuste », avec abandons : κ_m ∈ {0,1} « modèle gardé » (pénalité v_m ou ⌊v_m/2⌋),
y_g libre, et Σ_g y_g ≥ Σ_{m cible} κ_m (comptage par type ; là encore pas besoin de x[g,m]). Un multi-modèle
abandonné dans le type t libère ses créneaux des autres types (bonus non modélisé : le LNS les réutilise).

### 3.4 Autres leviers si c'est encore trop lent
- Fixer les décisions évidentes : y_g = 1 pour les générateurs à e_g = 1 et lb_g ≤ 1 000 ; f_m = 0 pour les modèles
  à coût réduit < −200 (hors marge) — déjà fait par la restriction 3.1.
- Fixer les classes « grosses » (s ≥ 4 000) par la LP et ne laisser entier que la monnaie.
- Boucle « offre effective » sur le MIP agrégé existant (sans datasets) : remplacer T_t par T_t − W_t et F_t par
  F_t − W_t^libre, où W_t est le gaspillage mesuré après réalisation ; 2–3 itérations. Peu coûteux, à utiliser en
  secours si le MIP6 ne converge pas.
- Solveur : **highspy directement** (pas `scipy.milp` : threads non réglables, cf. JOURNAL 20:20), options
  `threads`, `time_limit`, `mip_rel_gap`, écriture de l'incumbent périodique. Alternative CP-SAT (coefficients
  entiers, bon sur les sous-problèmes par type, `num_workers` = cœurs libres) : essayer les deux 60 s sur un type.

---

## 4. Enchaînement complet (pipeline `src/mip6.py`, à écrire demain)

### 4.0 Diagnostic (10 s, dès que des cœurs se libèrent)
Rejouer la réalisation des rôles `runs/mipr_6.json` en comptant : créneaux F non remplis, générateurs sans
données (par type, par lb), datasets restants par taille. Confirme §0.2 et calibre les largeurs de classes.
Mesurer aussi le gaspillage de `best/instance_6.json` par catégorie de créneau (`src/waste.py` + ventilation F/Y).

### 4.1 Étape A — rôles + classes (MIP6 joint, §3.1 + §3.2)
Entrée : `runs/lp_6.json` (duaux, support), marge K. Sortie : `runs/mip6_A.json` = rôles (f, h, y, z) + n_{k,s}.
Objectif : valeur (exacte). Hint : rôles du MIP agrégé et classes de `best/instance_6.json` (on sait convertir
la meilleure solution en classes : elle est admissible pour le modèle → le MIP part ≥ 667 214 en valeur agrégée).
Temps : 15–30 min, 8–12 threads. On accepte un gap non prouvé ; on garde la meilleure solution trouvée.
Attendu : valeur agrégée ≈ 669–670 k, et surtout **réalisable sans gaspillage caché**.

### 4.2 Étape B — rôles fixés, min consommation par type (§3.3)
Fixe f, h, y, z de A ; 4 MIP indépendants (1 par type, 1–3 threads chacun, 5 min) : min Σ s_mid(k) n_{k,s}.
Sortie : `runs/mip6_B.json`. Maximiser le reste de données pour le LNS.

### 4.3 Étape C — réalisation en datasets réels + subset-sum exact
1. Pour chaque classe k et chaque créneau s : prendre n_{k,s} datasets réels de la classe (datasets triés ;
   donner les plus petits aux créneaux dont Σ s_lo n est le plus au-dessus de lb : réduit déjà l'excès).
   Garantie : fenêtre respectée par construction conservative.
2. Appariement : par type, zipper les g (y_g = 1) avec les (m,t) (z = 1) → `modelMappings`.
3. **Polissage par subset-sum exact** (réutilise `Pools.fill_exact`) : créneaux par lb décroissant ; pour chaque
   créneau, remettre ses datasets dans le pool libre (pool = ses datasets + les datasets non affectés, petit) et
   relancer `fill_exact(lists, lb, ub)` (somme minimale ≥ lb, gros d'abord) ; répéter tant que la consommation
   baisse. Ne touche ni rôles ni appariement → toujours valide.
4. Export JSON entiers, `test_solution.py` via `save_if_better.py` (seule porte vers best/).
   Sortie : `runs/mip6_real.json`.

### 4.4 Étape D — LNS depuis la solution réalisée
`src/lns.py 6 --lp --start runs/mip6_real.json --roles runs/mip6_A.json --mu 1 --exact 300 --save --sync`, graines
multiples sur les cœurs libres. Le LNS exploite les données libérées en B/C (insertions `try_insert`) et les échanges.
Variante à ajouter si le temps le permet : mouvement « MIP par type sur un sous-ensemble » = `cp_move` élargi
(150–200 créneaux, pool complet du type, classes de taille, CP-SAT 5–10 s), déjà esquissé dans `cpsat_repair.py`.

### 4.5 Boucle (si A ne tient pas dans le temps)
Secours §3.4 : MIP agrégé avec offre effective T_t − W_t → réalisation exacte (C) → mesurer W_t → itérer 2–3 fois,
puis LNS. Ou A restreint au support sans marge (−700 créneaux) puis LNS plus long.

---

## 5. Taille estimée et budget temps (récapitulatif)
| modèle | variables | contraintes | solveur | temps visé |
|---|---|---|---|---|
| référence niveau dataset (§2) | ~45 M binaires | ~5 000 fenêtres + 5 000 datasets | — | impossible |
| niveau dataset, support + marge | ~4,5 M binaires | idem | HiGHS | LP ~10 min, MIP non |
| **A : joint, classes, support + marge (§3.1–3.2)** | ~200 k entiers + 10 k binaires | ~4 400 | HiGHS (highspy) | LP < 1 min, MIP 15–30 min |
| **B : par type, rôles fixés (§3.3)** | ~50 k entiers / type | ~1 100 / type | HiGHS ou CP-SAT, ×4 parallèle | 5 min |
| C : réalisation + polissage | — | — | Python (`fill_exact`) | < 1 min |
| D : LNS | — | — | `lns.py` | le reste de la journée |

Implémentation : ~2 h (construction des classes et des créneaux, modèle highspy, réalisation, tests de validité).
Lancer sur la machine dès la fin des runs de nuit (07:00 UTC) ; les 4 MIP de B sur 4 cœurs, A sur 8–12 threads.

## 6. Contrôles obligatoires
- Chaque solution réalisée passe par `save_if_better.py` (scoreur officiel) ; jamais d'écriture directe dans best/.
- Convertir `best/instance_6.json` en (rôles, classes) et vérifier qu'elle satisfait toutes les contraintes du
  modèle A (test de cohérence du modèle ; donne aussi le hint). Si elle les viole, le modèle est faux.
- Vérifier sur une solution de A que valeur agrégée = score officiel après réalisation C (sinon : une règle du
  scoreur manque ; relire ANALYSE.md « Ce que fait EXACTEMENT test_solution.py »).
- Logger : nb de créneaux à fenêtre vidée par l'agrégation, gap MIP, consommation par type, gaspillage avant/après
  polissage, énergie. Tout dans `logs/mip6_*.log`, runs > 1 min sous nohup/tmux avec `timeout`.
- Ne pas sur-apprendre l'instance 6 : le même code (classes + rôles) doit servir tel quel aux instances 2, 5, 7
  (agrégation par classes ; support LP + marge), où la LP est aussi quasi entière.

## 7. Risques et parades
- A trop lent / LP relâchée faible (fenêtres) → B seul sur les rôles du MIP agrégé avec abandons (version robuste),
  puis boucle offre effective (§3.4).
- Agrégation trop conservative (fenêtres vidées) → w plus fins pour la monnaie (w = 25 sous 500), ou deux passes :
  A grossier, puis B avec classes fines.
- Mémoire : 200 k colonnes × ~3 non-zéros ≈ négligeable ; CP-SAT par type avec 50 k entiers : OK sur 23 Go.
- Dépendance au `--roles` du LNS : `lns.py` lit f, h, y, z ; produire `runs/mip6_A.json` au même format que
  `runs/mip_4.json` pour ne rien changer au LNS.

## 8. Prochaine action (demain matin, dans l'ordre)
1. 07:00 UTC : fin des runs de nuit, `status.sh`, noter les scores dans JOURNAL.md.
2. Diagnostic §4.0 (10 s) → ajuster w et K.
3. Écrire `src/mip6.py` (A, B, C) + test de cohérence §6 sur best/instance_6.json.
4. Lancer A (30 min, nohup, log), B (5 min), C, `save_if_better`, puis D sur 10 cœurs ; garder 2 cœurs pour 2 et 5.
