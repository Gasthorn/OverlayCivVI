# Spec 01 : Mod d'Extraction des Données du Jeu (Civilization VI)

## 1. Objectif
Développer un mod Lua pour Civilization VI qui extrait l'état du jeu **tel que le joueur local le connaît** (brouillard de guerre respecté) et le transmet au service moteur via `Lua.log` à chaque début et fin de tour du joueur local.

## 2. Contraintes & Règles

### 2.1 Contexte d'exécution
- Le script s'exécute en **contexte UI**, déclaré dans le `.modinfo` via une action `AddUserInterfaces` (contexte `InGame`).
- Le contexte gameplay (`AddGameplayScripts`) est **interdit** : il a une vue omnisciente et n'expose pas le joueur local de façon fiable.

### 2.2 Visibilité (brouillard de guerre)
`Players[Game.GetLocalPlayer()]` **ne restreint rien** : en contexte UI, l'API peut lire les données de tous les joueurs et de toute la carte. Le respect du brouillard est donc une règle de code :
- **Données du joueur local** (villes, unités, technologies, dogmes, rendements, politiques) : extraction libre.
- **Tuiles** : n'extraire que les tuiles pour lesquelles `PlayersVisibility[localPlayer]:IsRevealed(x, y)` est vrai.
- **Ressources sur une tuile** : ne les exporter que si le joueur peut les voir (`player:GetResources():IsResourceVisible(resourceHash)`). Par exemple, les chevaux sont invisibles avant Élevage.
- **Autres joueurs** : uniquement ceux rencontrés (`player:GetDiplomacy():HasMet(otherId)`), et uniquement les informations publiques listées dans le schéma (§4).
- **Unités et villes adverses** : uniquement celles situées sur une tuile actuellement visible (`IsVisible(x, y)`).

### 2.3 Performance
- L'extraction et la sérialisation s'exécutent en **moins de 200 ms**. La durée est exportée dans `meta.extraction_ms`. `os.clock()` n'a qu'une résolution d'une seconde dans le jeu (session du 2026-10-29 : 107 mesures à 0 ms, une à 1000 ms). Le mod utilise donc `Automation.GetTime()` s'il est accessible, et indique au chargement dans `Lua.log` le chronomètre retenu (`chrono …`). Unité et précision restent à confirmer.
- Pas de parcours de toute la carte : les tuiles exportées se limitent à un **rayon de 3 autour de chaque ville du joueur** (le rayon d'exploitation d'une ville).

### 2.4 Sérialisation
- Sérialiseur JSON écrit en Lua 5.1, sans dépendance (`CivOvlJson.lua` : le préfixe évite une collision de nom dans le système de fichiers virtuel du jeu). Il gère :
  - les tables-tableaux et les tables-objets, avec des clés triées pour une sortie déterministe ;
  - l'échappement des chaînes, y compris les caractères de contrôle ;
  - les nombres non finis, exportés en `null` ;
  - `null` explicite via la sentinelle `CivOvlJson.null` (une valeur `nil` disparaît d'une table Lua) ;
  - les tables vides, exportées en `[]` par défaut, ou en `{}` si elles sont marquées avec `CivOvlJson.object(t)`.
- Les identifiants de types sont exportés sous forme de **chaîne `Type`** issue de `GameInfo` (ex. `"TECH_POTTERY"`), jamais sous forme d'index ou de hash.

## 3. Événements Déclencheurs
- `Events.LocalPlayerTurnBegin` → export avec `meta.trigger = "turn_begin"`.
- `Events.LocalPlayerTurnEnd` → export avec `meta.trigger = "turn_end"`.
- `Events.LoadScreenClose` → export initial avec `meta.trigger = "game_loaded"` (permet de reprendre une partie chargée).

> ✅ Les trois événements ont été validés en jeu le 2026-10-29 : `game_loaded` puis une paire `turn_begin`/`turn_end` par tour.

**Changements en cours de tour** (MVP 1) → export avec `meta.trigger = "state_changed"`, pour que les recommandations suivent les choix du joueur sans attendre le tour suivant :
- Événements écoutés, filtrés sur le joueur local : `Events.ResearchChanged`, `Events.CivicChanged`, `Events.CityProductionChanged`, `Events.GovernmentChanged` et `Events.CityAddedToMap`.
- Les rafales d'événements sont regroupées. Chaque événement marque l'état comme modifié, et un seul export a lieu sur `Events.GameCoreEventPublishComplete`, que le jeu déclenche après chaque série d'événements du moteur (même motif que `ResearchChooser.lua`).
- Historique : une première version reposait sur `ContextPtr:SetUpdate` et n'a produit aucun export pendant une session de 50 tours (2026-10-29), sans erreur. Remplacée ; la nouvelle version est à valider en jeu.

## 4. Protocole de Sortie (Lua.log)

### 4.1 Prérequis côté joueur
Aucun. `Lua.log` est écrit avec la configuration par défaut d'`AppOptions.txt` (constaté le 2026-10-29). Il se trouve dans `%LOCALAPPDATA%\Firaxis Games\Sid Meier's Civilization VI\Logs\`, et non dans `Documents` comme sur les anciennes versions du jeu. Les lignes y ont la forme `<Contexte>: <texte>`.

### 4.2 Format des lignes
Une ligne de `Lua.log` est préfixée par le jeu (nom du contexte). Le tailer cherche donc le marqueur **n'importe où** dans la ligne.

```
[CIVOVL] <msg_id> <part>/<total> <payload>
```

- `msg_id` : entier croissant au sein d'une session de jeu (`tour * 10 + séquence`, ou un simple compteur).
- `part` / `total` : index du fragment, à partir de 1, et nombre total de fragments.
- `payload` : tranche du JSON sérialisé, de **900 octets au plus** (marge de sécurité contre la troncature des lignes ; valeur à ajuster au MVP 0). Le découpage se fait à l'octet et peut couper un caractère UTF-8 : le moteur réassemble des octets et ne décode qu'à la fin.
- Le JSON complet est la concaténation des `payload` de `1` à `total` dans l'ordre.
- Les lignes de diagnostic du mod utilisent le marqueur `[CIVOVL-INFO]`, que le moteur ignore.

Exemple :
```
InGame: [CIVOVL] 121 1/3 {"schema_version":1,"meta":{"trigger":"turn_begin"...
InGame: [CIVOVL] 121 2/3 ..."cities":[{"city_id":65536,"name":"Rome"...
InGame: [CIVOVL] 121 3/3 ...]}
```

## 5. Schéma des Données (`game_state`, version 1)

Le schéma formel fait foi : `specs/schemas/game_state.schema.json`. Exemple abrégé :

```json
{
  "schema_version": 1,
  "meta": {
    "trigger": "turn_begin",
    "extraction_ms": 42,
    "game_id": "LEADER_TRAJAN_1849302"
  },
  "game": {
    "turn": 12,
    "game_speed": "GAMESPEED_STANDARD",
    "difficulty": "DIFFICULTY_PRINCE",
    "map_size": "MAPSIZE_STANDARD",
    "ruleset": "RULESET_EXPANSION_2",
    "era": "ERA_ANCIENT"
  },
  "player": {
    "player_id": 0,
    "civilization": "CIVILIZATION_ROME",
    "leader": "LEADER_TRAJAN",
    "government": "GOVERNMENT_CHIEFDOM",
    "policies": ["POLICY_DISCIPLINE"]
  },
  "yields": {
    "gold": 45.2,
    "gold_per_turn": 8.5,
    "science_per_turn": 12.1,
    "culture_per_turn": 9.4,
    "faith": 10.0,
    "faith_per_turn": 2.0
  },
  "techs": {
    "current_research": "TECH_HORSEBACK_RIDING",
    "research_progress": 45,
    "researched": ["TECH_POTTERY", "TECH_ANIMAL_HUSBANDRY"],
    "boosted": ["TECH_HORSEBACK_RIDING"]
  },
  "civics": {
    "current_civic": "CIVIC_FOREIGN_TRADE",
    "civic_progress": 80,
    "unlocked": ["CIVIC_CODE_OF_LAWS"],
    "boosted": []
  },
  "strategic_resources": { "RESOURCE_HORSES": 4 },
  "cities": [
    {
      "city_id": 65536,
      "name": "Rome",
      "is_capital": true,
      "hex_x": 14,
      "hex_y": 20,
      "population": 3,
      "housing": 5.0,
      "amenities_surplus": 1,
      "current_production": "BUILDING_MONUMENT",
      "production_progress": 15,
      "production_turns_left": 3,
      "districts": ["DISTRICT_CITY_CENTER"],
      "buildings": ["BUILDING_PALACE"]
    }
  ],
  "units": [
    {
      "unit_id": 131073,
      "type": "UNIT_SCOUT",
      "formation_class": "FORMATION_CLASS_LAND_COMBAT",
      "hex_x": 14,
      "hex_y": 22,
      "hp": 100,
      "moves_left": 2
    }
  ],
  "tiles": [
    {
      "hex_x": 15,
      "hex_y": 20,
      "terrain": "TERRAIN_GRASS",
      "feature": null,
      "resource": "RESOURCE_HORSES",
      "improvement": null,
      "owner": "self",
      "visible": true
    }
  ],
  "known_players": [
    {
      "player_id": 2,
      "civilization": "CIVILIZATION_GREECE",
      "leader": "LEADER_PERICLES",
      "at_war": false
    }
  ]
}
```

### Notes
- `progress` = valeur brute du jeu (points accumulés). `research_cost` et `civic_cost` donnent le coût réel de l'élément en cours (modificateurs compris), ce qui permet d'estimer les échéances.
- `techs.boosted` / `civics.boosted` : boosts obtenus pour des éléments **pas encore** recherchés ou adoptés.
- `cities[].coastal` : au moins une tuile adjacente est de l'eau (`plot:IsWater()`, mer ou lac). C'est la condition pour produire des unités navales.
- `tiles[].river` : `plot:IsRiver()`, exporté seulement s'il vaut `true`. Il sert d'estimation de l'adjacence des plateformes commerciales quand `district_sites` est absent.
- `cities[].district_sites` : pour chaque quartier ni construit ni en construction dans la ville, le **meilleur emplacement** parmi les tuiles de la ville (`Map.GetCityPlots():GetPurchasedPlots(city)`) : `{ "DISTRICT_CAMPUS": { "adjacency": 3, "hex_x": 15, "hex_y": 21 } }`.
  - La validité vient de `plot:CanHaveDistrict(district, joueur, ville)` et l'adjacence de la somme de `plot:GetAdjacencyYield(joueur, ville, district, rendement)` sur tous les rendements. C'est le calcul exact du jeu, mods compris, celui de l'écran de placement (`AdjacencyBonusSupport.lua`).
  - Quartiers évalués : Campus, Plateforme commerciale, Théâtre, Lieu saint, Zone industrielle, Campement et Port, ou la version unique de la civilisation du joueur quand elle existe (`DistrictReplaces`, avec le `TraitType` du quartier parmi les traits de la civilisation et du leader). Seuls ceux qui ont au moins un emplacement valide sont exportés.
  - ⚠️ `CanHaveDistrict` accepte aussi les quartiers uniques d'**autres** civilisations : une partie Kongo voyait Suguba, Thanh et Suk Dzong (constaté le 2026-10-29). Le mod les écarte, et le moteur filtre aussi de son côté (spec 02 §7).
  - Limite : seules les tuiles déjà possédées par la ville sont évaluées, pas celles qu'elle pourrait acheter.
- `settle_map` : carte de colonisation, exportée seulement sur `game_loaded` et `turn_begin`.
  - Contenu : `{ "map_width", "map_height", "tiles": [...] }` (`Map.GetGridSize()`).
  - Zone : les tuiles **révélées** à 8 tuiles ou moins d'une ville du joueur, ou à 5 tuiles ou moins d'un de ses colons (`Units.FoundCity`). Le balayage reste borné, sans parcours de la carte entière. Les abscisses sont ramenées dans la carte (`x % largeur`) pour les cartes qui bouclent.
  - Chaque tuile porte `hex_x`, `hex_y`, `terrain`, `feature`, et selon le cas `natural_wonder` (`Features.NaturalWonder`), `river` (`IsRiver`), `lake` (`IsLake`), `owner` (`"self"` / `"other"`), `city` (`IsCity`, `"self"` / `"other"`) et `resource` (si visible, `IsResourceVisible`). Les valeurs fausses ou vides sont omises.
  - L'eau douce, la côte et les distances sont déduites par le moteur (spec 02 §9).
- `cities[].wonder_sites` : exporté avec `plots` (`game_loaded`, `turn_begin`). Pour chaque merveille (`Buildings.IsWonder`) que la ville peut lancer maintenant (`city:GetBuildQueue():CanProduce(hash, true)`, comme `ProductionPanel.lua` : prérequis acquis, pas encore construite ailleurs), la liste des indices de tuiles où le jeu autorise à la placer : `CityManager.GetOperationTargets(city, CityOperationTypes.BUILD, {[PARAM_BUILDING_TYPE] = hash})[CityOperationResults.PLOTS]`, comme l'écran de placement (`StrategicView_MapPlacement.lua`). Ce sont les tuiles déjà achetées par la ville. Exemple : `{ "BUILDING_STONEHENGE": [1834, 1902] }`.
- `cities[].district_slots` : `{ "used": n, "allowed": m }`, à savoir les quartiers soumis à la population déjà zonés et le nombre autorisé (`GetNumZonedDistrictsRequiringPopulation` / `GetNumAllowedDistrictsRequiringPopulation`, comme l'écran de ville du jeu).
- `cities[].plots` : **carte détaillée** de la ville, exportée uniquement sur `game_loaded` et `turn_begin`, car elle est volumineuse. Le moteur garde la dernière reçue pour les autres déclencheurs. `district_sites` n'est lui aussi exporté qu'à ces moments-là.
  - Elle couvre les tuiles **révélées des 3 premiers anneaux** autour de la ville.
  - Chaque tuile porte `index`, `hex_x`, `hex_y`, `terrain`, `feature`, `resource` (si visible), `improvement`, `district` (`plot:GetDistrictType()`), `river`, `owned` (achetée par la ville), `neighbors`, et soit `sites`, soit `foreign: true` pour une tuile d'une autre civilisation.
  - `other_city` : nom d'une **autre ville du joueur** qui possède la tuile (`Cities.GetPlotPurchaseCity(plot)`, comme `CityPanel.lua`). Ses `sites` sont alors vides : aucun quartier de cette ville ne peut y être placé, mais son quartier éventuel est dessiné (spec 03 §4.4).
  - Quartiers évalués dans `sites` : en plus des quartiers de spécialité, les quartiers de soutien Aqueduc, Barrage, Complexe de divertissement et Quartier résidentiel, ainsi que la Place du gouvernement, le Quartier diplomatique, la Réserve naturelle, le Parc aquatique, l'Aérodrome et le Spatioport (ou leurs versions uniques). Les types absents de la configuration (DLC non installé) sont ignorés. Le Canal n'est pas évalué.
  - `CanHaveDistrict` **ignore les prérequis** (technologie, dogme) : une partie sans Théâtre et poésie recevait des `sites` de Théâtre (constaté le 2026-10-29). Les quartiers pas encore débloqués sont donc évalués aussi, ce qui permet de les planifier ; le moteur indique lesquels sont verrouillés (spec 02 §7).
  - `neighbors` liste les 6 indices voisins (`Map.GetAdjacentPlot(x, y, direction)`), -1 hors carte. Le moteur n'a ainsi aucune convention de grille à deviner.
  - `sites` donne, pour chaque quartier absent de la ville et que la tuile peut accueillir (`CanHaveDistrict`), l'adjacence calculée par le jeu sur la carte actuelle.
  - `district_sites` (le meilleur emplacement par quartier) est dérivé de ces mêmes calculs, sur toutes les tuiles non étrangères des 3 anneaux.
- `player.religion` : religion fondée par le joueur (`player:GetReligion():GetReligionTypeCreated()`, qui vaut -1 sans religion), ou `null`.
- `known_players[].name` : nom affiché en jeu, `Locale.Lookup(config:GetCivilizationShortDescription())`. Il couvre les civilisations de mods absentes de la base de traduction.
- `tiles[]` : `feature`, `resource`, `improvement` et `owner` sont omis quand ils sont vides. L'aménagement d'une tuile étrangère hors de vue n'est pas exporté, car il a pu changer depuis la dernière observation.
- Chaque section facultative est extraite séparément. Si une section échoue, elle est omise et l'erreur est signalée une fois par session dans `Lua.log` (`[CIVOVL-INFO] Section '…' ignorée : …`) ; les autres sections restent exportées.
- Les identifiants de type sont de simples chaînes non vides : des mods peuvent s'écarter de la convention `MAJUSCULES_SOULIGNÉS`.
- `game_id` : identifiant stable d'une partie, qui sert à archiver les tours. Il doit rester identique quand on recharge la partie ou qu'on redémarre le service. Format : `<leader>_<graine carte>_<graine partie>`, d'après `MapConfiguration.GetValue("RANDOM_SEED")` et `GameConfiguration.GetValue("GAME_SYNC_RANDOM_SEED")`. Une graine illisible est remplacée par `x`. Si les deux sont illisibles, le champ est omis et le moteur en génère un (spec 02 §3.1). Le repli du moteur, basé sur l'heure, crée un nouveau dossier d'archive à chaque redémarrage du service : constaté le 2026-10-29, d'où ce choix.
- `tiles[].owner` : `"self"`, `"other"` ou `null` (aucun propriétaire). Les tuiles révélées mais pas visibles actuellement ont `visible: false`.
- `strategic_resources` : présent uniquement avec Gathering Storm.

## 6. Sources API (MVP 0)
API indicative, reprise de l'UI du jeu (TopPanel). À valider en jeu.

| Champ | Source |
|---|---|
| `game.turn` | `Game.GetCurrentGameTurn()` |
| `player.civilization` / `leader` | `PlayerConfigurations[id]:GetCivilizationTypeName()` / `GetLeaderTypeName()` |
| `yields.gold` | `player:GetTreasury():GetGoldBalance()` |
| `yields.gold_per_turn` | `GetGoldYield() - GetTotalMaintenance()` (trésor) |
| `yields.science_per_turn` | `player:GetTechs():GetScienceYield()` |
| `yields.culture_per_turn` | `player:GetCulture():GetCultureYield()` |
| `yields.faith` / `faith_per_turn` | `player:GetReligion():GetFaithBalance()` / `GetFaithYield()` |
| `techs.current_research` | `GameInfo.Technologies[player:GetTechs():GetResearchingTech()].TechnologyType` |
| `techs.researched` / `boosted` / `research_cost` | `HasTech(i)`, `HasBoostBeenTriggered(i)`, `GetResearchCost(i)` (techs) |
| `civics.*` | `player:GetCulture()` : `GetProgressingCivic()`, `GetCulturalProgress(i)`, `GetCultureCost(i)`, `HasCivic(i)`, `HasBoostBeenTriggered(i)` |
| `player.government` / `policies` | `GetCurrentGovernment()`, `GetNumPolicySlots()`, `GetSlotPolicy(i)` (culture) |
| `game.era` / `game_speed` / `difficulty` / `map_size` / `ruleset` | `Game.GetEras():GetCurrentEra()`, `GameConfiguration.GetGameSpeedType()`, `PlayerConfigurations[id]:GetHandicapTypeID()`, `Map.GetMapSize()`, `GameConfiguration.GetRuleSet()` |
| `strategic_resources` | `player:GetResources():GetResourceAmount(type)` pour les ressources `RESOURCECLASS_STRATEGIC` |
| `cities[]` | `city:GetBuildQueue()` (`GetCurrentProductionTypeHash`, `Get*Progress`, `GetTurnsLeft`), `city:GetGrowth()` (`GetHousing`, `GetAmenities`, `GetAmenitiesNeeded`), `city:GetDistricts():Members()` + `IsComplete()`, `city:GetBuildings():HasBuilding(i)` |
| `units[]` | `player:GetUnits():Members()`, `GetMaxDamage() - GetDamage()`, `GetMovesRemaining()` |
| `tiles[]` | `Map.GetPlot`, `Map.GetPlotDistance`, `PlayersVisibility[id]:IsRevealed/IsVisible`, `GetResources():IsResourceVisible(hash)` |
| `known_players[]` | `PlayerManager.GetAliveMajorIDs()`, `GetDiplomacy():HasMet(id)` / `IsAtWarWith(id)` |

Toutes ces sources ont été vérifiées dans le code Lua officiel de l'UI du jeu (`Base/Assets/UI`). Les sections du MVP 1 restent à valider en jeu.

## 7. Installation
`scripts/install_mod.ps1` copie `src/mod/` dans `<Documents>\My Games\Sid Meier's Civilization VI\Mods\CivVISmartOverlay`. `<Documents>` est le dossier Documents réel de Windows, qui peut être redirigé vers OneDrive.

## 8. Tâches pour Claude Code
1. ✅ Créer `src/mod/CivVISmartOverlay.modinfo` (action `AddUserInterfaces`, contexte `InGame`).
2. ✅ Créer `src/mod/GameStateExporter.xml` (contexte UI vide) et `src/mod/GameStateExporter.lua`.
3. ✅ Implémenter `src/mod/CivOvlJson.lua` (sérialiseur, cf. §2.4).
4. ✅ Implémenter l'extraction section par section, en respectant les règles de visibilité du §2.2 (MVP 1, à valider en jeu).
5. ✅ Implémenter l'émission fragmentée (§4.2).
6. ✅ MVP 0 : se limiter à `meta`, `game.turn`, `player`, `yields` et `techs.current_research`.
