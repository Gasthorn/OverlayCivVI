# 🏛️ Civ VI Smart Overlay (SDD Project)

Un overlay intelligent et non-intrusif en direct pour **Civilization VI**, conçu selon la méthodologie **Spec-Driven Development (SDD)** avec **Claude Code**.

Le projet combine trois éléments :
- un mod Lua qui extrait les données en respectant le brouillard de guerre ;
- un service Python qui calcule des recommandations à partir des règles du jeu et d'heuristiques explicables ;
- une interface HUD transparente qui guide le joueur tour par tour.

---

## 🛠️ Architecture du Projet

```
Mod Lua ──print()──▶ Lua.log ──tail──▶ Service moteur (Python) ──WebSocket──▶ Overlay (PySide6)
```

```
├── specs/                       # Spécifications (SDD)
│   ├── 00-architecture.md
│   ├── 01-mod-extraction.md
│   ├── 02-recommendation-engine.md
│   ├── 03-overlay-ui.md
│   ├── 04-recommendations-contract.md
│   └── schemas/                 # JSON Schemas (font foi)
├── src/
│   ├── mod/                     # Code Lua & XML du mod Civ VI
│   ├── engine/                  # Tailer Lua.log, règles, stratégies, quartiers, colonisation, serveur WebSocket
│   ├── ui/                      # Overlay PySide6
│   ├── contracts.py             # Validation par JSON Schema, partagée moteur/UI
│   └── launcher.py              # Démarre service + overlay sans console
├── scripts/                     # Installation du mod et du raccourci, simulateur de partie
├── data/                        # Générés en local, non versionnés :
│   ├── game_state.json          #   dernier état reçu
│   ├── followed_strategies.json #   stratégie suivie par partie
│   ├── logs/                    #   logs du lanceur, du service et de l'overlay
│   └── raw/                     #   archives par tour (seulement si CIVOVL_ARCHIVE=1)
└── tests/                       # Tests unitaires + fixtures (base du jeu, game_state réels)
```

---

## 🚀 Fonctionnalités Clés

- **Extraction respectueuse du brouillard de guerre** : seules les informations connues du joueur local sont exportées. Les règles de visibilité sont appliquées explicitement (spec 01).
- **Recommandations explicables** : moteur de règles fondé sur la base de données du jeu (boosts Eureka, technologies débloquant des ressources visibles, villes inactives…) et scores de 7 stratégies (Rush Cavalerie, Armée médiévale, Plateformes commerciales, Victoire scientifique, Victoire culturelle, Victoire religieuse, Bataille navale), chacun avec ses facteurs.
- **Placement des quartiers** : le mod demande au jeu le meilleur emplacement de chaque quartier dans chaque ville (adjacence exacte, mods compris), et le moteur propose les villes où il rapporte le plus.
- **Conseiller LLM optionnel** *(à venir)* : actions supplémentaires en langage naturel.
- **HUD transparent en 4 pages** : *Actions* (le plan de votre stratégie, les urgences, les autres opportunités), *Stratégies* (choix et scores détaillés), *Villes* (schéma de chaque ville et disposition conseillée des quartiers) et *Colonisation* (meilleurs sites pour vos colons). Mode « click-through » commutable au raccourci clavier.
- **Disposition des quartiers** : pour chaque ville, l'overlay dessine une mini-carte et indique où placer chaque quartier manquant pour maximiser l'adjacence, interactions entre quartiers comprises (Port + Plateforme commerciale, quartiers voisins…).
- **Stratégie suivie** : en début de partie, l'overlay vous demande de choisir une stratégie. Les actions recommandées se concentrent ensuite sur elle : technologies et dogmes clés, quartiers aux meilleurs emplacements, bâtiments, unités, aménagements. Le choix est mémorisé pour chaque partie.
- **Merveilles de la stratégie** : l'overlay propose la prochaine merveille utile à votre stratégie, dans la ville qui peut la construire, et réserve son emplacement sur la carte de la ville pour que les quartiers voisins en profitent.
- **Colonisation** : sur la partie découverte de la carte, l'overlay classe les meilleurs sites où fonder vos prochaines villes (eau douce, ressources, collines, distance à vos villes…) et rappelle d'y envoyer votre colon.
- **Archivage des parties (optionnel)** : avec `CIVOVL_ARCHIVE=1`, chaque tour est archivé dans `data/raw/`, en vue d'un futur modèle ML entraîné sur vos propres parties. L'overlay n'en a pas besoin : l'archivage est désactivé par défaut pour ne pas remplir le disque (plusieurs Mo par partie).

Feuille de route détaillée : [specs/00-architecture.md](specs/00-architecture.md#6-feuille-de-route).

---

## 💻 Développer avec Claude Code (SDD)

Chaque prompt doit référencer la spec concernée :

```bash
claude "Ajoute une règle selon specs/02-recommendation-engine.md §5, avec son test sur fixture"
claude "Exporte un nouveau champ selon specs/01-mod-extraction.md et mets à jour game_state.schema.json"
claude "Ajoute une section à la page Villes selon specs/03-overlay-ui.md §4"
```

Toute modification d'un message JSON passe d'abord par la spec et le schéma concernés. `schema_version` est incrémenté si le changement est incompatible (les messages moteur → overlay sont en version 2).

---

## ⚙️ Installation & Démarrage

### Prérequis
- Windows 10/11 et **Civilization VI** (PC). Les extensions *Rise and Fall* et *Gathering Storm* sont prises en charge, mais pas obligatoires.
- **Python 3.10 ou plus récent**, avec le lanceur `py` (option « py launcher » de l'installeur python.org).
- Le jeu en mode **fenêtré** ou **fenêtré sans bordure** (*Options ▸ Graphismes*) : le plein écran exclusif masque l'overlay.

### 1. Récupérer le projet et installer les dépendances
```powershell
git clone https://github.com/Gasthorn/OverlayCivVI.git OverlayCivVI
cd OverlayCivVI
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
Toutes les commandes suivantes se lancent depuis la racine du projet. Elles appellent directement `.\.venv\Scripts\python.exe` : pas besoin d'activer l'environnement virtuel.

> Si PowerShell refuse d'exécuter les scripts `.ps1` (« l'exécution de scripts est désactivée »), autorisez-les une fois pour votre compte :
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```
> ou lancez-les au cas par cas : `powershell -ExecutionPolicy Bypass -File .\scripts\install_mod.ps1`.

### 2. Installer le mod dans Civ VI
```powershell
.\scripts\install_mod.ps1
```
Le script copie le contenu de `src/mod/` dans `<Documents>\My Games\Sid Meier's Civilization VI\Mods\CivVISmartOverlay`. `<Documents>` est le dossier Documents réel de Windows, souvent `OneDrive\Documents` : le script le détecte tout seul.

Ensuite, dans le jeu :
1. Lancez Civ VI et ouvrez **Extras ▸ Mods**.
2. Cochez **Civ VI Smart Overlay**.
3. Lancez une nouvelle partie ou chargez une sauvegarde. Le mod ne modifie que l'interface (`AffectsSavedGames = 0`) : on peut l'activer ou le désactiver sur une partie existante sans risque pour la sauvegarde.

Aucun réglage du jeu n'est nécessaire : `Lua.log` est écrit avec la configuration par défaut.

**Mise à jour du mod** : quand `src/mod/` change (après un `git pull` par exemple), relancez `install_mod.ps1`, puis rechargez la partie. Le jeu ne relit les fichiers du mod qu'au chargement.

**Vérifier que le mod tourne** : une fois en partie, le log du jeu doit contenir des lignes `[CIVOVL]`.
```powershell
Select-String -Path "$env:LOCALAPPDATA\Firaxis Games\Sid Meier's Civilization VI\Logs\Lua.log" -Pattern CIVOVL | Select-Object -Last 3
```

### 3. Lancer l'overlay
Depuis une icône sur le bureau, à créer une seule fois :
```powershell
.\scripts\install_shortcut.ps1
```
Le raccourci **Civ VI Smart Overlay** démarre le service et l'overlay sans console. Fermer l'overlay arrête aussi le service. Les logs sont dans `data/logs/`.

Ou séparément, avec les logs dans la console :
```powershell
# Service moteur (lit Lua.log, publie sur ws://127.0.0.1:8765)
.\.venv\Scripts\python.exe src/engine/service.py

# Overlay
.\.venv\Scripts\python.exe src/ui/main.py
```

L'overlay peut démarrer avant ou après le jeu. Le moteur lit les règles dans `DebugGameplay.sqlite`, que Civ VI régénère à chaque lancement de partie (ruleset et mods compris) : lancez au moins une partie avant le tout premier démarrage.

Raccourcis : `Ctrl+Alt+O` bascule entre click-through et interactif, `Ctrl+Alt+H` affiche ou masque l'overlay, `Ctrl+Alt+P` passe à la page suivante, `Ctrl+Alt+V` à la ville suivante (page Villes). En mode interactif, cliquez sur les onglets ou sur « Suivre » pour choisir une stratégie, faites glisser l'overlay pour le déplacer, et cliquez sur « × » pour le fermer.

### Emplacements et variables d'environnement
Les chemins sont détectés automatiquement. Ces variables permettent de les surcharger :

| Variable | Valeur par défaut |
|---|---|
| `CIVOVL_LUA_LOG` | `%LOCALAPPDATA%\Firaxis Games\Sid Meier's Civilization VI\Logs\Lua.log` |
| `CIVOVL_GAMEPLAY_DB` | `…\Cache\DebugGameplay.sqlite` (même dossier Firaxis) |
| `CIVOVL_LOCALIZATION_DB` | `…\Cache\DebugLocalization.sqlite` |
| `CIVOVL_LANGUAGE` | langue du jeu (`DisplayLanguage` dans `UserOptions.txt`), sinon `fr_FR` |
| `CIVOVL_GAME_DIR` | dossier d'installation Steam du jeu (traductions des DLC) |
| `CIVOVL_DATA_DIR` | `data/` du projet |
| `CIVOVL_ARCHIVE` | `0` : `1` archive chaque tour dans `data/raw/<game_id>/` |
| `CIVOVL_WS_PORT` | `8765` |
| `CIVOVL_POLL_INTERVAL` | `0.25` (secondes) |

Pour activer l'archivage sur votre machine seulement, définissez la variable une fois pour votre compte Windows. Elle vaut aussi pour le raccourci du bureau ; relancez l'overlay pour qu'elle soit prise en compte :
```powershell
setx CIVOVL_ARCHIVE 1
```

### Dépannage
- **L'overlay reste vide** : vérifiez que le mod est coché dans *Extras ▸ Mods* et que `Lua.log` contient des lignes `[CIVOVL]` (voir plus haut). Après une mise à jour du projet, réinstallez le mod.
- **L'overlay n'apparaît pas au-dessus du jeu** : passez Civ VI en fenêtré sans bordure.
- **Le raccourci du bureau ne fait rien** : consultez `data/logs/`, ou lancez le service et l'overlay à la main pour voir les erreurs.

### Tester sans Civ VI
```powershell
.\.venv\Scripts\python.exe scripts/simulate_game.py data/fake_Lua.log       # terminal 1
$env:CIVOVL_LUA_LOG = "data/fake_Lua.log"; .\.venv\Scripts\python.exe src/engine/service.py   # terminal 2
.\.venv\Scripts\python.exe src/ui/main.py                                   # terminal 3
```

### Tests
```powershell
.\.venv\Scripts\python.exe -m pytest
```
