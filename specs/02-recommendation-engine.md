# Spec 02 : Service Moteur de Recommandation

> Remplace l'ancienne `02-ml-pipeline.md`. L'apprentissage par renforcement (PPO) est retiré du périmètre : Civ VI n'est pas un environnement simulable (pas de mode headless, pas d'API pour injecter des actions, plusieurs secondes par tour), et les « scores de stratégie » n'ont pas de vérité terrain. Le ML revient en §7 comme évolution, alimentée par les données archivées.

## 1. Objectif
Un service Python local qui :
1. lit `Lua.log` et reconstitue les messages `game_state` (spec 01) ;
2. les valide, les archive, puis calcule des recommandations à partir des **règles du jeu** (base de données de Civ VI) et d'**heuristiques** explicables ;
3. publie le résultat sur un WebSocket local, selon le contrat de la spec 04.

Lancement : `python src/engine/service.py`.

## 2. Modules

| Module | Rôle |
|---|---|
| `src/engine/config.py` | Configuration (chemins, port), surchargeable par variables d'environnement `CIVOVL_*` |
| `src/engine/log_tailer.py` | Suit `Lua.log` (y compris quand le jeu le tronque ou le recrée au lancement), extrait les lignes `[CIVOVL]` et réassemble les fragments |
| `src/engine/state.py` | Validation via `specs/schemas/game_state.schema.json`, et dataclasses typées |
| `src/engine/session.py` | Attribution du `game_id` (§3.1) |
| `src/engine/recommendations.py` | Construction des messages `status` et `recommendations` (spec 04) |
| `src/contracts.py` | Chargement des JSON Schemas, partagé entre le moteur et l'UI |
| `src/engine/game_db.py` | Chargement des données de règles du jeu (technologies, dogmes, boosts, coûts, unités, vitesses) |
| `src/engine/archive.py` | Écrit `data/game_state.json` (dernier état) et `data/raw/<game_id>/turn_XXXX_<trigger>.json` |
| `src/engine/rules/` | Une règle par fichier (cf. §5) |
| `src/engine/milestones.py` | Jalons passés et à venir (cf. §5.4) |
| `src/engine/strategies.py` | Scores de stratégie (cf. §6.1 à §6.3) |
| `src/engine/strategy_focus.py` | Actions de focus pour la stratégie suivie (cf. §6.5) |
| `src/engine/preferences.py` | Stratégie suivie, mémorisée par partie (cf. §6.5) |
| `src/engine/city_layout.py` | Disposition des quartiers et carte des villes (cf. §7) |
| `src/engine/strategies.py` | Scores de stratégie heuristiques (cf. §6) |
| `src/engine/advisor_llm.py` | Conseiller LLM optionnel (cf. §6.3) |
| `src/engine/ws_server.py` | Serveur WebSocket (spec 04) |
| `src/engine/service.py` | Assemble le tout (boucle asyncio) |

## 3. Réception (`log_tailer`)
- Chemin par défaut : `%LOCALAPPDATA%\Firaxis Games\Sid Meier's Civilization VI\Logs\Lua.log` (emplacement des versions récentes du jeu, constaté le 2026-10-29). Repli sur `<Documents>\My Games\Sid Meier's Civilization VI\Logs\Lua.log`, où `<Documents>` est le dossier Documents réel de Windows (`FOLDERID_Documents`, éventuellement redirigé vers OneDrive). Surchargeable par `CIVOVL_LUA_LOG`.
- Lecture incrémentale : on mémorise la position. Si la taille du fichier diminue, ou si le fichier est recréé, on repart du début.
- Au démarrage, le fichier est lu depuis le début : le dernier état de la partie en cours est ainsi récupéré.
- Réassemblage en octets. Le mod émet les fragments d'un message à la suite, donc un seul message est en cours d'assemblage à la fois. Le message en cours est abandonné, avec un warning, dans quatre cas :
  - un fragment d'un `msg_id` différent arrive ;
  - le `total` d'un fragment ne correspond pas ;
  - un numéro de fragment déjà reçu revient (`msg_id` réutilisé après un rechargement du mod) ;
  - 10 s se sont écoulées depuis le dernier fragment.
- Un JSON invalide ou hors schéma est logué, puis ignoré. Le service ne doit jamais crasher sur une donnée d'entrée.

### 3.1 `game_id`
- S'il est fourni par le mod (`meta.game_id`), il est utilisé tel quel.
- Sinon, le moteur génère `<leader>_<AAAAMMJJ-HHMMSS>` au premier état reçu. Il le conserve tant que le leader ne change pas et que le tour ne recule pas. Un recul du tour (chargement d'une sauvegarde antérieure) ouvre une nouvelle branche, avec un nouvel identifiant.

## 4. Données de règles (`game_db`)
- Source principale : la base SQLite que le jeu génère, `%LOCALAPPDATA%\Firaxis Games\Sid Meier's Civilization VI\Cache\DebugGameplay.sqlite` (même logique de repli que pour `Lua.log`). Elle reflète le ruleset et les mods de la dernière partie lancée.
- Tables et colonnes lues : voir `TABLES` dans `src/engine/game_db.py` (technologies, dogmes et prérequis, boosts, unités, bâtiments, quartiers, aménagements, ressources, remplacements uniques, traits de civilisation et de leader, vitesses, ères, gouvernements).
- La base est rechargée quand le jeu la régénère, c'est-à-dire quand son `mtime` change (nouvelle partie, autres mods).
- **Noms affichés** : ils sont lus dans `DebugLocalization.sqlite` (table `LocalizedText`), dans la langue du jeu (`DisplayLanguage` de `UserOptions.txt`, surchargeable par `CIVOVL_LANGUAGE`).
  - Le cache ne contient pas toujours les traductions des extensions : en fr_FR, « Barrage », « Place de la gouvernance », « Réserve » ou « Parc aquatique » y manquaient (constaté le 2026-10-29). Les textes absents dans la langue du jeu sont donc cherchés dans les fichiers `DLC/*/Text/*.xml` de l'installation (`engine/game_text.py`, éléments `Replace` ou `Row` avec `Tag` et `Language`), hors scénarios et variantes `_China`. Seuls les fichiers contenant un tag cherché sont analysés, ce qui prend environ 3 s au chargement.
  - Dossier d'installation : `CIVOVL_GAME_DIR`, sinon la clé de désinstallation Steam `Steam App 289070` (`InstallLocation`). Introuvable : étape ignorée.
  - Repli ensuite sur `en_US`. Pour les formes `singulier|pluriel`, seul le singulier est gardé. Un type sans texte devient un libellé lisible (`UNIT_MY_THING` → « My thing »).
- **Disponibilité** : un élément est disponible si tous ses prérequis sont acquis. Les éléments sans prérequis hors de la première ère (ère du futur de Gathering Storm) ne sont jamais proposés, car d'autres conditions les débloquent.
- **Éléments uniques** : `resolve_for_player` renvoie la version que la civilisation peut réellement construire, d'après les traits de la civilisation et du leader et les tables `*Replaces` (ex. Hypaspiste au lieu d'Épéiste pour la Macédoine). Pour compter ce que possède le joueur, on inclut les variantes uniques.
- **Normalisation de la vitesse** : toute durée exprimée « en tours » dans les règles et les jalons est définie à la vitesse Standard, puis convertie avec `GameSpeeds.CostMultiplier / 100`. Par exemple, « tour 30 » en Standard correspond au tour 60 en Épique.
- Si la base est introuvable ou illisible, le service passe en mode dégradé : aucune règle n'est évaluée, le snapshot et les jalons restent publiés, et un statut `degraded` est envoyé avec la raison.
- Fixture de test : `tests/fixtures/game_db.sql`, extraite de la vraie base par `scripts/extract_game_db_fixture.py`.

## 5. Moteur de Règles

### 5.1 Interface
```python
class Rule(Protocol):
    id: str                       # ex. "eureka_reachable"
    def evaluate(self, state: GameState, db: GameDb) -> list[Action]: ...
```
- Une règle est **pure et déterministe**, sans entrée-sortie, testable à partir d'une fixture.
- Chaque `Action` produite porte un `reason` lisible par le joueur et une `priority` (cf. spec 04).
- Une exception levée par une règle est loguée. La règle est ignorée pour ce tour, les autres continuent.

### 5.2 Règles du MVP 1
| id | Déclencheur | Action proposée | Priorité |
|---|---|---|---|
| `idle_research` | Aucune recherche (ou aucun dogme) en cours alors qu'il en existe de disponibles | Choisir une technologie ou un dogme | 90 |
| `idle_city` | Ville sans production en cours | Choisir une production | 85 |
| `boosted_available` | Un élément disponible a déjà son boost et n'est pas en cours | Le rechercher ou l'adopter | 70 (40 si l'élément en cours est lui aussi boosté) |
| `eureka_reachable` | Le boost d'un élément disponible s'obtient en produisant au plus 2 éléments que le joueur peut déjà réaliser | Produire, construire ou aménager l'élément | 60 (70 si c'est l'élément en cours) |
| `unlock_visible_resource` | Des ressources visibles près des villes, sur des tuiles non étrangères et non aménagées, attendent une technologie disponible | Rechercher cette technologie | 50 + 3 × nb (5 au maximum) |
| `housing_cap` | Population ≥ logement − 1 | Grenier s'il est constructible, sinon « Augmenter le logement » | 50 (65 si population ≥ logement) |

Types de boost couverts par `eureka_reachable` : `TRAIN_UNIT`, `OWN_X_UNITS_OF_TYPE`, `CONSTRUCT_BUILDING`, `HAVE_X_BUILDINGS` (seulement si le quartier requis existe), `HAVE_X_DISTRICTS` et `HAVE_X_IMPROVEMENTS`. Les autres types sont ignorés et seront modélisés progressivement.

Une unité navale (`Units.Domain = DOMAIN_SEA`) n'est proposée que si au moins une ville est côtière (`cities[].coastal`). Si le champ est absent, on ne bloque pas.

### 5.3 Fusion et tri
- Deux actions qui ont la même catégorie et la même cible (`target.type`, `city_id`, `unit_id`) sont fusionnées. On garde la plus prioritaire, on concatène les raisons avec « · », et la priorité gagne +5 (100 au maximum).
- Les actions sont triées par priorité décroissante.
- Les listes sont recalculées sur `game_loaded`, `turn_begin` et `state_changed`. Sur `turn_end`, seul le snapshot change.

### 5.4 Jalons (`src/engine/milestones.py`)
- **Passés** : ils sont détectés en comparant les états successifs. Ce sont la fondation de la capitale ou d'une ville, un changement de gouvernement et une nouvelle ère. Au premier état d'une partie, l'historique est reconstruit à partir des archives `data/raw/<game_id>/`. Les 6 derniers sont publiés.
- **À venir** : l'échéance de la recherche et du dogme en cours, calculée par `tour + ⌈(coût − progrès) / rendement par tour⌉` et préfixée par « ≈ ».
- Partie reprise en cours de route (premier état observé après le tour 5, sans archive) : les villes déjà présentes sont enregistrées sans jalon, pour ne pas inventer de fondation « au tour actuel ».

## 6. Scores de Stratégie

### 6.1 Principe
Chaque stratégie est une **fonction heuristique documentée**, qui renvoie un score entre `0.0` et `1.0` et la liste des facteurs qui y contribuent (affichés dans l'UI). Pas de modèle opaque.

### 6.2 Calcul
- Score = (somme pondérée des facteurs **additifs**, dont les poids somment à 1) × (produit des **multiplicateurs**).
- Un multiplicateur de valeur `v` applique un coefficient `0,3 + 0,7 × v`. Il représente une condition sans laquelle la stratégie perd l'essentiel de son intérêt.
- Chaque facteur vaut entre 0 et 1. Les tours sont normalisés à la vitesse Standard (§4).
- Ordre des facteurs affichés : un multiplicateur pénalisant (`v < 0,5`) en premier, puis les facteurs additifs non nuls par contribution décroissante, puis les multiplicateurs favorables.
- Seules les tuiles non étrangères sont prises en compte.

### 6.3 Stratégies v1
| id | Facteurs additifs (poids) | Multiplicateur |
|---|---|---|
| `cavalry_rush` | Chevaux près des villes ou en réserve (0,40) · progression vers Équitation (0,25) · voisin rencontré, ou en guerre (0,20) · cavalerie unique (0,15) | Timing : 1 jusqu'au tour normalisé 40, puis décroissance linéaire jusqu'à 0 au tour 90 |
| `medieval_army` | Fer près des villes ou en réserve (0,25) · progression vers Étriers (0,20) · voisin (0,20) · campements existants (0,15) · unité ou campement unique (0,20) | Fenêtre médiévale : 0 au tour normalisé 30, 1 de 70 à 140, 0 à 200 |
| `commercial_hub_rush` | Progression vers Monnaie (0,25) · emplacement de plateforme commerciale (0,25) · or par tour (0,20) · villes côtières (0,10) · plateformes existantes (0,10) · bonus unique (0,10) | — |
| `science_campus` | Emplacement de campus (0,30) · progression vers Écriture (0,20) · science par tour (0,20) · campus existants (0,20) · bonus unique (0,10) | — |
| `culture_victory` | Culture par tour (0,30) · emplacement de théâtre (0,20) · progression vers le dogme Art dramatique et poésie (0,15) · théâtres existants (0,15) · villes avec merveille (0,10) · bonus unique (0,10) | — |
| `religious_victory` | Foi par tour (0,25) · religion fondée (0,20 ; sinon jusqu'à 0,5 tant que le tour normalisé est sous 80) · emplacement de lieu saint (0,20) · lieux saints existants (0,15) · progression vers Astrologie (0,10) · bonus unique (0,10) | — |

- **Facteur d'emplacement** : quand `cities[].district_sites` est exporté (spec 01), il vaut la moyenne des 2 meilleures adjacences libres (calculées par le jeu) divisée par 3, plafonnée à 1. Son libellé est « Meilleur emplacement de Campus : +4 à Kwango ». Sinon on utilise une estimation à partir des tuiles : rivières (commerce), montagnes + ½ jungles (campus), montagnes + ½ forêts (lieu saint), ou rien (théâtre).
- **Progression vers un dogme** : même formule que pour une technologie, sur l'arbre des dogmes.

- **Progression vers une technologie** : 1 si elle est acquise, sinon `1 − étapes/4`, +0,15 si le boost est obtenu (0,95 au maximum). `étapes` compte la technologie elle-même et ses prérequis manquants.
- **Bonus unique** : la civilisation possède un remplacement unique de l'élément clé (unité, quartier ou bâtiment).
- Pondérations dans `src/engine/strategies.py`, documentées en docstring. Toute modification d'une pondération s'accompagne d'une mise à jour des tests (`tests/test_strategies.py`).
- Calibrage de référence : vraie partie Kongo au tour 50, vitesse En ligne → Focus Scientifique 0,78, Rush Commercial 0,44, Rush Cavalerie 0,26.

### 6.5 Stratégie suivie (`src/engine/strategy_focus.py`)
Le joueur peut suivre une stratégie depuis l'overlay (spec 04 §4). Le choix est mémorisé par partie dans `data/followed_strategies.json` (`src/engine/preferences.py`).

**Plan déclaratif par stratégie** (`PLANS`) :

| Stratégie | Étapes clés (technologies ou dogmes) | Quartier → bâtiments | Unités (effectif visé) | Aménagements |
|---|---|---|---|---|
| `cavalry_rush` | Équitation, Étriers | Campement → Écurie *ou* Caserne | Chevalier, Coursier, Cavalier, Char lourd (4) ; 4 villes visées | Pâturage sur chevaux |
| `medieval_army` | Étriers, Tactique militaire, Génie militaire | Campement → Caserne *ou* Écurie → Armurerie | Chevalier, Homme d'armes, Arbalétrier, Épéiste (6) | Mine sur fer |
| `commercial_hub_rush` | Monnaie, Banque | Plateforme commerciale → Marché → Banque | — | — |
| `science_campus` | Écriture, Éducation | Campus → Bibliothèque → Université | — | — |
| `culture_victory` | *Art dramatique et poésie*, *Humanisme* (dogmes) | Théâtre → Amphithéâtre → Musée d'art *ou* d'archéologie | — | — |
| `religious_victory` | Astrologie, *Théologie* (dogme) | Lieu saint → Sanctuaire → Temple | Apôtre, Missionnaire (3), seulement si une religion est fondée | — |

- Recherche : au plus une technologie et un dogme, à savoir le prochain pas vers la première étape clé manquante de chaque arbre.
- Bâtiments : chaque maillon de la chaîne peut lister des alternatives. Il est acquis dès que l'une est construite (Caserne et Écurie sont exclusives dans le jeu).
- **Choix des villes pour le quartier** : quand `district_sites` est exporté, les villes sans emplacement valide sont écartées et les autres sont classées par adjacence (« meilleur emplacement, adjacence +3 »). Si aucun emplacement candidat n'a de bonus (ex. Campement), ou sans données, on classe par population.

**Actions de focus** (champ `strategy`, raison préfixée par le nom de la stratégie) :

| Action | Priorité |
|---|---|
| Recherche : prochaine technologie disponible vers la première technologie clé non acquise (la moins chère du chemin). Aucune si c'est déjà la recherche en cours. | 78 |
| Quartier dans les 2 meilleures villes (adjacence, sinon population) qui ne l'ont pas et ne le produisent pas | 77, puis 76 |
| Bâtiment : le premier maillon manquant de la chaîne, dans chaque ville qui a le quartier | 72 |
| Unités : produire l'unité la plus avancée disponible, jusqu'à l'effectif visé (variantes uniques comprises) | 70 |
| Aménagements des gisements du joueur non exploités | 70 |

**Actions communes à toutes les stratégies** (mêmes champ `strategy` et préfixe) :

| Action | Condition | Priorité |
|---|---|---|
| **Colon** dans la ville la plus peuplée (≥ 2 habitants) qui n'en produit pas | Ère antique, classique ou médiévale ; `villes + colons en cours < city_target` (6 par défaut, 4 pour `cavalry_rush`) ; aucun colon déjà possédé ou en production (un à la fois) | 75 |
| **Quartier hors quota** (`RequiresPopulation = 0`), au plus un par ville, le plus prioritaire : | version du joueur débloquée, absente de la ville et non en production, avec un emplacement valide quand `district_sites` est connu | |
| · Aqueduc (ou Thermes) | logement saturé (`population ≥ logement − 1`) | 74 |
| · Quartier résidentiel (ou Mbanza) | logement saturé et Aqueduc impossible ou déjà construit | 73 |
| · Barrage | emplacement connu (plaine inondable) | 71 |
| **Bâtisseur** dans la ville la plus peuplée qui n'en produit pas | `bâtisseurs + en production < min(villes, ⌈ressources à aménager / 3⌉)`. Une ressource compte si elle est sur une tuile du joueur, non aménagée, avec un aménagement débloqué | 71 |

La raison d'un quartier hors quota indique le logement apporté (`Districts.Housing`, ex. « +5 logements » pour la Mbanza) et « hors quota de quartiers ». La population sert d'indicateur de production pour choisir la ville productrice.

Les éléments uniques de la civilisation sont utilisés (`resolve_for_player`).

**Effet sur les autres actions** : quand une stratégie est suivie, les actions ordinaires de priorité inférieure à 80 perdent 15 points. Les actions urgentes (≥ 80 : rien en cours, ville inactive) restent en tête. La fusion du §5.3 s'applique ensuite, et l'action fusionnée conserve le champ `strategy`.

### 6.6 Conseiller LLM (optionnel, MVP 2)
- Désactivé par défaut (`ADVISOR_LLM=0`). La clé d'API se lit dans `.env`.
- Entrée : `game_state` résumé, sorties des règles et des scores. Sortie : au plus 3 actions supplémentaires au format `Action` (spec 04), avec `source: "llm"`.
- Appel asynchrone, au plus un par `turn_begin`, avec un timeout de 30 s. Un échec n'empêche jamais la publication des résultats des règles.

### 6.7 Merveilles de la stratégie (`src/engine/wonders.py`)
Chaque plan liste ses merveilles clés par ordre de priorité (`PLANS[...].wonders`) :

| Stratégie | Merveilles |
|---|---|
| `cavalry_rush` | Armée de terre cuite |
| `medieval_army` | Armée de terre cuite, Alhambra, Statue de Zeus |
| `commercial_hub_rush` | Colosse, Pétra, Grand Zimbabwe, Big Ben |
| `science_campus` | Grande bibliothèque, Université de Sankoré, Université d'Oxford |
| `culture_victory` | Oracle, Colisée, Cité interdite, Théâtre Bolchoï, Ermitage, Christ Rédempteur, Broadway, Opéra de Sydney |
| `religious_victory` | Stonehenge, Temple de la Mahabodhi, Sainte-Sophie, Kōtoku-in, Temple de Mînâkshî, Mont-Saint-Michel |

- **Choix** (`wonder_pick`) : la première merveille du plan qui n'est pas déjà construite par le joueur et qu'une ville peut lancer (`cities[].wonder_sites`, spec 01 : prérequis acquis, pas construite ailleurs). Si une merveille du plan est déjà en production, rien n'est proposé : une seule à la fois.
- **Emplacement** : parmi les tuiles autorisées par le jeu, celle qui maximise `bonus aux quartiers voisins existants − 0,5 × meilleure adjacence de quartier de la tuile − malus de ressource bonus + 0,5 × population de la ville`.
  - Le bonus vient des règles « merveille voisine » (`Adjacency_YieldChanges.AdjacentWonder`, ex. `Wonder_Culture` : Place du théâtre +2 avec BBG). Une merveille ne compte pas comme « quartier voisin » pour les autres règles.
  - La population sert d'indicateur de production pour départager les villes.
- **Sans `wonder_sites`** (état antérieur au champ) : la première merveille du plan débloquée par les technologies et dogmes, dans la ville la plus peuplée, sans emplacement.
- **Action** : « Construire <merveille> à <ville> », priorité 74. La raison donne l'intérêt de la merveille (`WONDER_NOTES`, ex. « Grand Prophète gratuit : fonde une religion très tôt » pour Stonehenge), « emplacement conseillé sur la page Villes » et le bonus apporté aux voisins.
- **Carte de la ville** (§7) : la tuile choisie est réservée (`plan_layout(..., reserved)`). Aucun quartier ne s'y place, mais les quartiers prévus autour profitent de la merveille (ex. Place du théâtre +2). La merveille est la première entrée de `layout` (`wonder: true`, `kind: DISTRICT_WONDER`, `focus: true`, `status: now`), avec pour adjacence le bonus apporté aux quartiers voisins, existants ou prévus.
- **Limite** : le jeu ne donne que les tuiles déjà achetées par la ville (comme son écran de placement) : une meilleure tuile à acheter n'est pas proposée.

## 7. Disposition des quartiers (`src/engine/city_layout.py`)
Pour chaque ville dont la carte détaillée est connue (`cities[].plots`, spec 01), le moteur propose où placer les quartiers manquants.

- **Zone** : les tuiles révélées des 3 premiers anneaux, achetées ou non. Les tuiles d'une autre civilisation (`foreign`) et celles d'une autre ville du joueur (`other_city`) sont exclues ; leurs quartiers comptent quand même comme voisins.
- **Ressources** (classe lue dans `Resources.ResourceClassType`) :
  - les tuiles portant un **luxe**, une ressource **stratégique** ou un **site archéologique** (antiquités, épaves) visibles ne reçoivent jamais de quartier ;
  - une ressource **bonus** est supprimée par le quartier : elle coûte `BONUS_RESOURCE_PENALTY = 0,5` dans la valeur optimisée, donc une case vide est préférée à valeur proche ;
  - les ressources pas encore révélées sont invisibles par construction (brouillard respecté, spec 01 §2.2) et ne peuvent pas être anticipées ;
  - `district_sites` est **recalculé par le moteur** à partir de la carte (`best_sites_from_plots`), avec les mêmes règles, et remplace celui du mod, qui ignore les ressources.
- **Cache** : le mod n'exporte la carte et les meilleurs emplacements (`district_sites`) qu'en début de tour. `CityPlotsCache` garde la dernière version de chaque ville et la vide quand la partie change. `enrich` reporte `district_sites` sur les états des autres déclencheurs, pour les règles et les scores.
- **Quartiers de soutien** : l'Aqueduc (ou le Bain), le Barrage, le Complexe de divertissement et le Quartier résidentiel (ou la Mbanza) sont planifiés comme les autres. Leur valeur vient surtout des bonus qu'ils donnent à leurs voisins (Aqueduc → Zone industrielle +2, etc.). Ceux qui ne consomment pas d'emplacement de population (`Districts.RequiresPopulation = 0`) sont toujours « maintenant » et marqués `uses_slot: false`.
- **Stratégie suivie** : l'adjacence produite par son quartier (`PLANS[...].district`) compte double dans la valeur optimisée (`FOCUS_WEIGHT = 2`). Il obtient donc les cases disputées, et il est marqué `focus: true`.
- **Candidats** : les quartiers présents dans au moins un `sites` d'une tuile possédée, réduits à ceux que le joueur peut construire : pour chaque type générique, `resolve_for_player` donne la version unique de sa civilisation s'il en a une, sinon le générique. Les quartiers uniques d'autres civilisations, que le jeu déclare valides, sont écartés. Le même filtre s'applique à `best_site` (choix des villes du §6.5 et facteur d'emplacement du §6.2).
- **Valeur d'un placement** :
  - l'adjacence de base calculée par le jeu (`sites`) ;
  - plus les interactions avec les quartiers **prévus** voisins, dans les deux sens ;
  - plus le gain apporté aux quartiers **existants** voisins (hors merveilles).
- **Interactions** : `GameDb.district_interaction`, d'après `District_Adjacencies` et `Adjacency_YieldChanges`. On ne garde que les règles « tout quartier voisin » (`OtherDistrictAdjacent`, `YieldChange / TilesRequired` par voisin) et « à côté de tel quartier » (`AdjacentDistrict`, variantes uniques comprises). Les prérequis et les obsolescences (technologies, dogmes) sont respectés, et `ExcludedAdjacencies` s'applique selon les traits du joueur. Exemple de la base réelle : Port voisin d'une Plateforme commerciale = +2,5 pour la plateforme.
- **Recherche** : on place d'abord de façon gloutonne (meilleur gain à chaque étape), puis on améliore localement : on déplace un quartier tant que la valeur totale augmente, en 3 passes au maximum.
- **Quartiers pas encore débloqués** : ils sont planifiés comme les autres (le mod en donne les `sites`, spec 01), pour réserver dès maintenant leur meilleure case. Chaque entrée porte `unlocked` et `requires` (nom de la technologie ou du dogme manquant, `GameDb.missing_prereq`). Un quartier verrouillé est toujours « plus tard », ne consomme pas les emplacements « maintenant », et vient après les quartiers débloqués. L'overlay ne les affiche que sur demande (spec 03 §4.4).
- **Limites par empire et exclusivités** (`excluded_districts`) :
  - un quartier limité par empire (`Districts.MaxPerPlayer`, ex. Place du gouvernement, Quartier diplomatique) n'est proposé que dans la **capitale**, et plus du tout une fois la limite atteinte ;
  - deux quartiers exclusifs dans une même ville (`MutuallyExclusiveDistricts`, ex. Complexe de divertissement et Parc aquatique) : si l'un est construit, l'autre est écarté ; sinon seul le premier placé par la recherche gloutonne (le meilleur) est gardé.
- **Ordre et statut** : le quartier de la stratégie suivie vient en premier, puis Campus, Plateforme commerciale, Lieu saint, Théâtre, Zone industrielle, Port, Place du gouvernement, Campement, Quartier diplomatique, Réserve, divertissement, quartiers de soutien, Aérodrome et Spatioport ; à rang égal, la meilleure adjacence passe d'abord. Les quartiers débloqués passent avant les verrouillés. Parmi les débloqués, les `allowed − used` premiers sont « maintenant », les suivants « plus tard ».
- **Grille de dessin** : `odd_rows_shifted` déduit des voisins donnés par le jeu quelles rangées sont décalées. Chaque tuile reçoit une position de dessin `x = hex_x (+0,5 si sa rangée est décalée)` et `y = hex_y`.
- **Limites** :
  - un quartier posé sur une tuile retire son élément (forêt, jungle), ce qui peut réduire l'adjacence des voisins : ce n'est pas modélisé ;
  - les règles propres à un leader sont écartées par `ExcludedAdjacencies` pour les autres. Par exemple, BBG réserve « Mbanza +2 » à Nzinga Mbande, et Mvemba ne l'a pas (vérifié le 2026-10-29). Une règle de mod sans exclusion serait comptée pour tous ;
  - le coût d'achat des tuiles non achetées n'est pas pris en compte ;
  - les adjacences d'un quartier verrouillé sont calculées sur la carte actuelle : des bonus qui dépendent d'une technologie ou d'un dogme futurs ne sont pas anticipés.

## 9. Sites de colonisation (`src/engine/settling.py`)
À partir de `settle_map` (spec 01), le moteur propose où fonder les prochaines villes, sur la partie découverte de la carte uniquement (brouillard respecté).

- **Grille** (`HexGrid`) : rangées décalées, avec la convention déduite des cartes de villes (`odd_rows_shifted`, reportée dans `settle_map` par `CityPlotsCache.enrich`). La carte boucle d'est en ouest. Les distances sont calculées en coordonnées axiales.
- **Cache** : la carte n'est exportée qu'en début de tour ; `CityPlotsCache` garde la dernière et la reporte sur les autres déclencheurs.
- **Sites possibles** : tuile de terre (ni côte, ni océan, ni montagne), sans merveille naturelle, sans ville, pas en territoire étranger. Elle doit être à 4 tuiles au moins de toute ville connue (règle du jeu) et à 6 tuiles au plus de la ville du joueur la plus proche. Sans ville (début de partie), cette dernière limite ne s'applique pas.
- **Score** : somme de facteurs, chacun affiché comme raison.

| Facteur | Poids |
|---|---|
| Eau douce : rivière sur la tuile, lac ou oasis voisin | +4 |
| Sinon côte (eau voisine qui n'est pas un lac) | +2 |
| Ni l'un ni l'autre | −1 |
| Sur une colline | +1,5 |
| Luxe visible à 3 tuiles ou moins | +2 par sorte, +0,5 par exemplaire en plus |
| Luxe absent de l'empire | +1 par sorte |
| Ressource stratégique visible | +1,5 par sorte, +0,375 par exemplaire en plus |
| Ressource bonus | +0,7 chacune |
| Merveille naturelle à 3 tuiles ou moins | +2 |
| Terres dans les 2 premiers anneaux : prairie, plaine (collines comprises), montagne | +0,15 par tuile |
| Terres pauvres : désert, toundra, neige (sauf plaine inondable) | −0,2 par tuile |
| Tuile déjà à une ville du joueur (chevauchement) | −0,4 chacune |
| Tuile étrangère dans le rayon | −0,5 chacune |
| Ville étrangère à 5 tuiles ou moins (loyauté, frontière) | −3 |
| Ville étrangère à 6 ou 7 tuiles | −1 |
| À 4 ou 5 tuiles d'une ville du joueur (empire compact) | +1 |

  Le 3e anneau compte à 60 % pour les ressources ; les tuiles non révélées ne comptent pas.
- **Choix** : les 5 meilleurs sites, espacés d'au moins 4 tuiles entre eux pour pouvoir tous être fondés.
- **Règle `settle_site`** (§5) : si le joueur a un colon, l'action « Fonder une ville sur le site n°1 (page Colonisation) », de catégorie `unit` et de priorité 76, avec les 3 premières raisons et la ville la plus proche.
- **Limites** :
  - pas de calcul de rendement exact par tuile ;
  - les ressources non encore révélées par les technologies sont invisibles ;
  - l'attrait, la loyauté et les barbares ne sont pas modélisés.

## 8. Évolution ML (hors v1)
- Les archives `data/raw/` forment le jeu de données. Le format est figé par `schema_version`.
- Pistes envisagées : imitation des choix du joueur (technologie, production), prédiction des rendements à N tours. Le RL n'est envisagé que si un simulateur exploitable apparaît.
- Avant toute implémentation, une spec dédiée (`specs/05-ml.md`) devra définir le jeu de données, la cible et la métrique.

## 8. Tâches pour Claude Code
1. ✅ `log_tailer.py` + tests (fragments désordonnés, UTF-8 coupé, fichier tronqué, timeout).
2. ✅ `state.py` (validation par schéma, dataclasses).
3. ✅ `archive.py`.
4. ✅ `ws_server.py` + `service.py` → **MVP 0** : publier un message `recommendations` qui ne contient que `snapshot`.
5. ✅ `game_db.py`, puis les règles du §5.2, une par une, avec leurs tests.
6. ✅ `milestones.py` (§5.4).
7. ✅ `strategies.py` (MVP 2).
8. `advisor_llm.py` (MVP 2, optionnel).
