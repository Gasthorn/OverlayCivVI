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
│   ├── engine/                  # Tailer Lua.log, moteur de règles, serveur WebSocket
│   └── ui/                      # Overlay PySide6
├── data/                        # Dernier état + archives de parties (JSON)
├── tests/                       # Tests unitaires + fixtures de game_state réels
├── .gitignore
└── README.md
```

---

## 🚀 Fonctionnalités Clés

- **Extraction respectueuse du brouillard de guerre** : seules les informations connues du joueur local sont exportées. Les règles de visibilité sont appliquées explicitement (spec 01).
- **Recommandations explicables** : moteur de règles fondé sur la base de données du jeu (boosts Eureka, technologies débloquant des ressources visibles, villes inactives…) et scores de 6 stratégies (Rush Cavalerie, Armée médiévale, Rush Commercial, Focus Scientifique, Victoire culturelle, Victoire religieuse), chacun avec ses facteurs.
- **Placement des quartiers** : le mod demande au jeu le meilleur emplacement de chaque quartier dans chaque ville (adjacence exacte, mods compris), et le moteur propose les villes où il rapporte le plus.
- **Conseiller LLM optionnel** : actions supplémentaires en langage naturel.
- **HUD transparent en 4 pages** : *Actions* (le plan de votre stratégie, les urgences, les autres opportunités), *Stratégies* (choix et scores détaillés), *Villes* (schéma de chaque ville et disposition conseillée des quartiers) et *Jalons*. Mode « click-through » commutable au raccourci clavier.
- **Disposition des quartiers** : pour chaque ville, l'overlay dessine une mini-carte et indique où placer chaque quartier manquant pour maximiser l'adjacence, interactions entre quartiers comprises (Port + Plateforme commerciale, quartiers voisins…).
- **Stratégie suivie** : en début de partie, l'overlay vous demande de choisir une stratégie. Les actions recommandées se concentrent ensuite sur elle : technologies et dogmes clés, quartiers aux meilleurs emplacements, bâtiments, unités, aménagements. Le choix est mémorisé pour chaque partie.
- **Archivage des parties** : chaque tour est archivé dans `data/raw/`, en vue d'un futur modèle ML entraîné sur vos propres parties.

Feuille de route détaillée : [specs/00-architecture.md](specs/00-architecture.md#6-feuille-de-route).

---

## 💻 Développer avec Claude Code (SDD)

Chaque prompt doit référencer la spec concernée :

```bash
claude "Implémente src/mod/GameStateExporter.lua selon specs/01-mod-extraction.md (périmètre MVP 0)"
claude "Implémente src/engine/log_tailer.py et ses tests selon specs/02-recommendation-engine.md §3"
claude "Crée la fenêtre overlay PySide6 selon specs/03-overlay-ui.md"
```

---

## ⚙️ Installation & Démarrage

### Prérequis
- Civilization VI (PC), en mode **fenêtré** ou **fenêtré sans bordure** : le plein écran exclusif masque l'overlay.
- Python 3.10+ :
  ```powershell
  py -m venv .venv
  .\.venv\Scripts\Activate.ps1
  pip install -r requirements.txt
  ```

### 1. Installation du Mod
```powershell
.\scripts\install_mod.ps1
```
Le script copie `src/mod/` dans `<Documents>\My Games\Sid Meier's Civilization VI\Mods\CivVISmartOverlay`. `<Documents>` est le dossier Documents réel de Windows (souvent `OneDrive\Documents`). Activez ensuite le mod dans **Extras ▸ Mods**.

### 2. Lancement
Depuis une icône sur le bureau, à créer une seule fois :
```powershell
.\scripts\install_shortcut.ps1
```
Le raccourci **Civ VI Smart Overlay** démarre le service et l'overlay sans console. Fermer l'overlay arrête aussi le service. Les logs sont dans `data/logs/`.

Ou séparément, avec les logs dans la console :
```powershell
# Service moteur (lit Lua.log, publie sur ws://127.0.0.1:8765)
python src/engine/service.py

# Overlay
python src/ui/main.py
```

Raccourcis : `Ctrl+Alt+O` bascule entre click-through et interactif, `Ctrl+Alt+H` affiche ou masque l'overlay, `Ctrl+Alt+P` passe à la page suivante, `Ctrl+Alt+V` à la ville suivante (page Villes). En mode interactif, cliquez sur les onglets ou sur « Suivre » pour choisir une stratégie, faites glisser l'overlay pour le déplacer, et cliquez sur « × » pour le fermer.

### Tester sans Civ VI
```powershell
python scripts/simulate_game.py data/fake_Lua.log          # terminal 1
$env:CIVOVL_LUA_LOG = "data/fake_Lua.log"; python src/engine/service.py   # terminal 2
python src/ui/main.py                                      # terminal 3
```
