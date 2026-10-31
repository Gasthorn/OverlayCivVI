# Directives Projet : Civ VI Smart Overlay (SDD)

## 🎯 Philosophie Spec-Driven Development (SDD)
- Avant d'écrire ou modifier du code, **consulte toujours les spécifications** dans `/specs/` (commencer par `specs/00-architecture.md`).
- Les JSON Schemas de `specs/schemas/` font foi sur les exemples des specs.
- N'invente pas de nouvelles structures de données JSON ou d'API sans mettre à jour la spec et le schéma correspondants (et incrémenter `schema_version` si le changement est incompatible).
- Si une implémentation s'écarte de la spec, demande confirmation ou propose une mise à jour du fichier de spec.

---

## 🛠️ Commandes Utiles

### Python
L'environnement virtuel se trouve dans `.venv` (Python 3.14, lancé via `py`). `python` n'est pas dans le PATH : utiliser `.\.venv\Scripts\python.exe`.
- **Installer les dépendances** : `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`
- **Lancer le service moteur** : `.\.venv\Scripts\python.exe src/engine/service.py`
- **Lancer l'overlay UI** : `.\.venv\Scripts\python.exe src/ui/main.py`
- **Simuler une partie** : `.\.venv\Scripts\python.exe scripts/simulate_game.py data/fake_Lua.log` (avec `CIVOVL_LUA_LOG` pointant dessus)
- **Exécuter les tests** : `.\.venv\Scripts\python.exe -m pytest`

### Mod Lua / Civ VI
`<Documents>` désigne le dossier Documents réel de Windows (ici redirigé vers OneDrive).
- **Installer le mod** : `.\scripts\install_mod.ps1`
- **Dossier Cible Mod** : `<Documents>\My Games\Sid Meier's Civilization VI\Mods\CivVISmartOverlay`
- **Log de sortie du mod** : `%LOCALAPPDATA%\Firaxis Games\Sid Meier's Civilization VI\Logs\Lua.log` (et non `Documents`)
- **Base de règles du jeu** : `%LOCALAPPDATA%\Firaxis Games\Sid Meier's Civilization VI\Cache\DebugGameplay.sqlite`

---

## 📐 Conventions & Styles

### Python
- Utiliser Python 3.10+ avec typage explicite (`type hints`).
- UI en PySide6. Ne jamais faire d'I/O bloquante ni de calcul lourd dans le thread UI (QtWebSockets, QThread ou asyncio).
- Loguer les erreurs d'extraction ou de validation JSON sans faire crasher le service ni l'overlay.
- Les règles du moteur sont des fonctions pures, testées sur les fixtures de `tests/fixtures/`.

### Lua (Civ VI)
- Le mod tourne en **contexte UI** (`AddUserInterfaces`), jamais en contexte gameplay.
- Pas de `io` dans le sandbox : la seule sortie est `print()` vers `Lua.log`, avec le protocole fragmenté `[CIVOVL]` (spec 01 §4).
- `Players[Game.GetLocalPlayer()]` **ne filtre pas** le brouillard de guerre : appliquer explicitement les règles de visibilité de la spec 01 §2.2 (`PlayersVisibility`, `IsResourceVisible`, `HasMet`).
- Éviter les boucles sur la carte entière ; se limiter aux tuiles proches des villes du joueur.
- Exporter les identifiants sous forme de chaîne `Type` de `GameInfo`, en JSON strict.

---

## 📁 Références Rapides
- **Architecture & feuille de route** : `specs/00-architecture.md`
- **Spec Extraction (mod Lua)** : `specs/01-mod-extraction.md`
- **Spec Moteur de recommandation** : `specs/02-recommendation-engine.md`
- **Spec Overlay UI** : `specs/03-overlay-ui.md`
- **Contrat Moteur ↔ UI** : `specs/04-recommendations-contract.md`
- **Schémas** : `specs/schemas/game_state.schema.json`, `specs/schemas/recommendations.schema.json`
