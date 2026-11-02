# Spec 00 : Architecture & Flux de Données

## 1. Objectif
Décrire les composants du système, leurs frontières et les canaux qui les relient. Toute nouvelle interface entre composants doit être ajoutée ici avant d'être implémentée.

## 2. Vue d'ensemble

```
┌──────────────────────┐   print()    ┌─────────────┐   tail    ┌────────────────────────────┐  WebSocket  ┌──────────────┐
│ Mod Lua (contexte UI)│ ───────────▶ │  Lua.log    │ ────────▶ │ Service moteur (Python)    │ ──────────▶ │ Overlay UI   │
│ GameStateExporter    │  messages    │ (fichier du │           │ log_tailer → engine →      │  messages   │ (PySide6)    │
│ spec 01              │  fragmentés  │  jeu)       │           │ ws_server        spec 02   │  spec 04    │ spec 03      │
└──────────────────────┘              └─────────────┘           └─────────────┬──────────────┘             └──────────────┘
                                                                              │ écrit
                                                                              ▼
                                                               data/game_state.json (dernier état)
                                                               data/raw/<game_id>/turn_XXXX.json (archive)
```

### Pourquoi ce découpage
- **Le Lua de Civ VI ne peut pas écrire de fichiers** (pas de bibliothèque `io` dans le sandbox). Le seul canal de sortie simple et fiable est `print()`, qui écrit dans `Lua.log`.
- **Le jeu ne peut pas recevoir de données externes** de façon simple. Le flux est donc à sens unique : jeu → Python → UI. (Le port FireTuner permettrait un retour, mais il est hors périmètre v1.)
- **L'UI ne fait aucun calcul métier** : elle affiche ce que le moteur publie.

## 3. Composants

| Composant | Emplacement | Spec | Processus |
|---|---|---|---|
| Mod d'extraction | `src/mod/` | 01 | Dans le jeu (contexte UI) |
| Service moteur | `src/engine/` | 02 | `python src/engine/service.py` |
| Overlay | `src/ui/` | 03 | `python src/ui/main.py` |
| Lanceur | `src/launcher.py` | 00 §3.1 | `pythonw src/launcher.py` |
| Contrat moteur → UI | `specs/schemas/recommendations.schema.json` | 04 | — |
| Contrat UI → moteur | `specs/schemas/client_messages.schema.json` | 04 §4 | — |
| Contrat mod ↔ moteur | `specs/schemas/game_state.schema.json` | 01 | — |

### 3.1 Lanceur
Démarre le service moteur et l'overlay en un seul geste, sans console, depuis un raccourci sur le bureau créé par `scripts/install_shortcut.ps1`. Il n'ajoute aucun canal entre les composants : ce sont deux processus enfants, qui restent lançables séparément.
- **Instance unique** : un mutex Windows nommé. Un second lancement affiche un message et s'arrête, sans rien démarrer.
- **Durée de vie** : l'overlay décide. Quand il se ferme, le lanceur arrête le service et se termine. Les enfants sont placés dans un job Windows, pour qu'ils s'arrêtent aussi si le lanceur est tué.
- **Logs** : `data/logs/launcher.log`, `service.log` et `overlay.log` (sous `CIVOVL_DATA_DIR` si la variable est définie), réécrits à chaque lancement.
- **Erreurs** : si un processus ne démarre pas ou si l'overlay se termine sur une erreur, un message indique le dossier des logs.

## 4. Contrats & Versionnage
- Chaque message échangé porte un champ `schema_version` (entier). Toute modification incompatible du schéma l'incrémente.
- Les schémas formels (JSON Schema draft 2020-12) se trouvent dans `specs/schemas/`. Ils font foi sur les exemples des specs en cas de divergence.
- Le moteur **valide** chaque `game_state` reçu. Un message invalide est logué et ignoré ; il ne fait jamais crasher le service.

## 5. Périmètre v1
- Parties **solo** uniquement (pas de multijoueur).
- Ruleset : jeu de base + Rise & Fall + Gathering Storm. Les champs propres à une extension sont optionnels dans le schéma.
- Windows uniquement.

## 6. Feuille de route

| Étape | Contenu | Critère de sortie |
|---|---|---|
| **MVP 0** ✅ | Mod minimal (tour, rendements, recherche) → tailer → overlay affichant l'état brut | Le chiffre d'or affiché dans l'overlay change à chaque tour sans redémarrage (validé en jeu le 2026-10-29) |
| **MVP 1** ✅ | Schéma complet (spec 01) + base de données du jeu + moteur de règles → panels Jalons et Actions | Au moins 5 règles actives et couvertes par des tests sur fixtures (6 règles ; validé en jeu sur 50 tours le 2026-10-29) |
| **MVP 2** | Scores de stratégie heuristiques + conseiller LLM optionnel → panel Stratégies | Scores reproductibles sur fixtures (heuristiques ✅ testées sur une vraie partie ; conseiller LLM non commencé) |
| **Plus tard** | ML supervisé sur les parties archivées dans `data/raw/` | Jeu de données ≥ 20 parties |

## 7. Tests
- `tests/fixtures/` contient des `game_state` réels capturés en jeu (au moins un par phase : tour ≤ 10, 20-50, 50+). Au MVP 0, une fixture synthétique sert de point de départ ; elle sera remplacée par une capture réelle.
- Chaque composant Python se teste sans lancer le jeu, à partir de ces fixtures ou d'extraits de `Lua.log`.
- `scripts/simulate_game.py` écrit une partie simulée dans un faux `Lua.log`, pour tester la chaîne moteur → overlay sans Civ VI.
