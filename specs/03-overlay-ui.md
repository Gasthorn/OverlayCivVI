# Spec 03 : Interface Graphique Overlay

## 1. Objectif
Une application desktop **PySide6** qui se superpose à Civilization VI et affiche, en temps réel, les messages publiés par le service moteur (spec 04). L'UI ne fait **aucun calcul métier**.

Lancement : `python src/ui/main.py`, ou avec le service moteur via le lanceur (spec 00 §3.1).

## 2. Prérequis d'Affichage
- Civ VI doit tourner en **mode fenêtré ou fenêtré sans bordure**. En plein écran exclusif, aucune fenêtre externe ne peut s'afficher par-dessus le jeu.
- Quand l'overlay ne peut pas s'afficher au-dessus du jeu, il doit rester utilisable **sur un second écran** (simple fenêtre normale).

## 3. Exigences d'Interface

### 3.1 Fenêtre
- Flags : `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool` (pas d'entrée dans la barre des tâches), et attribut `Qt.WA_TranslucentBackground`.
- Fond semi-transparent (opacité réglable, 85 % par défaut), thème sombre défini dans `src/ui/styles/dark.qss`.

### 3.2 Modes d'interaction
| Mode | Comportement |
|---|---|
| `click_through` (par défaut) | `Qt.WindowTransparentForInput` : les clics passent au jeu |
| `interactive` | La fenêtre reçoit les clics : onglets, choix de stratégie, déplacement, redimensionnement, sections repliables |
| `hidden` | Fenêtre masquée |

- Raccourcis globaux, enregistrés avec `RegisterHotKey` (Win32, via `ctypes`), **pas** de hook clavier global :
  - `Ctrl+Alt+O` : passer de `click_through` à `interactive` et inversement ;
  - `Ctrl+Alt+H` : afficher ou masquer ;
  - `Ctrl+Alt+P` : page suivante (Actions → Stratégies → Villes → Jalons), utilisable en click-through ;
  - `Ctrl+Alt+V` : ville suivante sur la page Villes (ouvre la page si besoin).
- La position, la taille, l'opacité et l'état replié des sections sont sauvegardés dans `%APPDATA%\CivVISmartOverlay\ui.json`.
- En mode `interactive`, un bouton « × » quitte l'overlay et une poignée permet de le redimensionner ; un clic-glisser n'importe où le déplace.

### 3.3 Connexion
- Client WebSocket vers `ws://127.0.0.1:8765`, avec `QtWebSockets` (intégré à la boucle Qt, pas de thread bloquant).
- Reconnexion automatique avec un délai croissant (1 s, 2 s, 4 s, puis 10 s au maximum).
- Un bandeau d'état reflète le dernier message `status` (spec 04) : `connecting`, `waiting_for_game`, `ok`, `degraded`.
- **Données périmées** : si le `turn` du dernier `recommendations` reçu est inférieur au `turn` du dernier `status`, le texte s'affiche grisé avec la mention « en attente d'analyse ».

## 4. Pages
L'overlay est organisé en **5 pages**, une seule visible à la fois, avec des onglets en tête (« Actions », « Stratégies », « Villes », « Colonisation », « Jalons ») et `Ctrl+Alt+P` pour passer à la suivante.

**Bascule automatique** (`OverlayWindow._update_auto_page`) :
- Nouvelle partie (`game_id` différent) ou changement de `followed_strategy` : page **Actions** si une stratégie est suivie, page **Stratégies** sinon. En début de partie, l'overlay demande donc de choisir une stratégie, et le choix bascule sur les actions.
- Le reste du temps (nouveau tour, même stratégie), la page affichée ne change pas.

**Mode interactif automatique** pendant le choix de stratégie :
- Quand l'overlay ouvre la page Stratégies faute de stratégie suivie, il passe de lui-même en mode `interactive` s'il était en `click_through`, pour que le bouton « Suivre » soit cliquable.
- Une fois la stratégie choisie, il revient en `click_through`, mais seulement si c'est lui qui avait activé le mode interactif.
- Un changement manuel (`Ctrl+Alt+O`) annule ce retour automatique : le mode choisi par le joueur est conservé.

L'UI n'applique pas le choix de stratégie elle-même : elle envoie `follow_strategy` (spec 04 §4), puis attend le message `recommendations` recalculé.

### 4.1 Page Actions (`actions`, `strategies`, `followed_strategy`)
- **En-tête** : « ★ <stratégie suivie> · <score> % » et un lien « Changer », qui ouvre la page Stratégies. Sans stratégie : « Aucune stratégie suivie » et un lien « Choisir une stratégie ».
- **Sections**, quand une stratégie est suivie :
  1. *À faire maintenant* : actions sans `strategy` et de priorité ≥ 80 (urgences : rien en cours, ville inactive). Masquée si vide.
  2. *Plan : <stratégie>* : actions dont `strategy` est la stratégie suivie, 6 au maximum, avec un titre doré. Le préfixe « <stratégie> : » des raisons est retiré, car redondant avec le titre de section.
  3. *Autres opportunités (N)* : les autres actions, dans une section repliable, **repliée par défaut** (état mémorisé, clé `other_actions`).
- Sans stratégie suivie : une seule liste « Actions recommandées » avec toutes les actions.
- Chaque action : icône par `category`, `title`, `reason` en sous-texte, badge « IA » si `source == "llm"`. Au-delà du maximum de la section, un « +N » dépliable.

### 4.2 Page Stratégies (`strategies`, `followed_strategy`)
- Invite en tête : « Choisissez une stratégie pour cette partie… », ou rappel de la stratégie suivie.
- Une carte par stratégie, par score décroissant : icône, nom, barre (score × 100 %), bouton « Suivre » (« ★ Suivie » pour la stratégie suivie, qui arrête le suivi si on clique dessus), puis les 3 premiers `factors`. La carte suivie a un liseré doré.

### 4.4 Page Villes (`cities`)
- **Menu déroulant** des villes, « Nom (population) ». La ville choisie reste sélectionnée d'une mise à jour à l'autre. `Ctrl+Alt+V` passe à la ville suivante, et ouvre d'abord la page si elle n'est pas affichée ; il fonctionne en click-through.
- Ligne « Quartiers : used/allowed · N emplacements libres ».
- Case à cocher « Inclure les quartiers pas encore débloqués » (décochée par défaut, mémorisée dans `ui.json`, clé `show_locked_districts`). Décochée, les entrées `unlocked: false` sont masquées de la carte et de la légende. Cochée, elles apparaissent avec un cercle en points fins et le statut « 🔒 <prérequis> ». La disposition est la même dans les deux cas : le moteur réserve toujours les cases des quartiers futurs.
- **Mini-carte hexagonale** (`ui/widgets/hex_map.py`), nord en haut. Elle ne fait que dessiner les positions `x`, `y` fournies par le moteur :
  - couleur par terrain (collines plus sombres, montagnes en gris) ;
  - tuiles à acheter légèrement atténuées, tuiles d'une autre civilisation très atténuées et hachurées en rouge ;
  - **frontière actuelle de la ville** : trait blanc sur les côtés des tuiles achetées (`owned`) dont la voisine ne l'est pas, calculé à partir des seules positions `x`, `y` ;
  - point vert foncé pour une forêt ou une jungle. Les rivières (`river`) ne sont pas dessinées : le moteur les utilise pour la disposition, mais le mod ne sait pas quels côtés de la tuile elles longent ;
  - ressource selon `resource_kind` : petit point jaune pour une ressource bonus ; losange cerclé de blanc pour une ressource protégée (luxe en violet, stratégique en orange, site archéologique en brun) ;
  - quartiers existants **de la ville** (tuile `owned`, ni `foreign` ni `other_city`) : icône sur un disque sombre cerclé de blanc ; quartiers d'**une autre ville** du joueur ou d'une autre civilisation : icône seule, estompée (opacité 0,4), pour ne pas confondre deux quartiers du même type ;
  - quartiers conseillés : cercle pointillé (doré si « maintenant », gris si « plus tard »), icône et adjacence prévue.
- **Nombre de quartiers conseillés affichés** : liste déroulante à côté de la case à cocher (3, 5, 8 ou tous ; 5 par défaut, mémorisé dans `ui.json`, clé `layout_limit`, 0 = tous). Seuls les N premiers, dans l'ordre conseillé, sont dessinés sur la carte et listés. Une ligne « +N autres quartiers masqués » signale les autres.
- **Merveille de la stratégie** (`wonder: true`) : dessinée et listée comme un quartier conseillé (icône 🗿, ★, adjacence = bonus aux voisins), avec le statut « merveille, maintenant ».
- **Quartiers conseillés** (titre « Quartiers conseillés ») : une ligne par quartier conseillé, avec icône, nom (précédé de ★ pour le quartier de la stratégie suivie), adjacence et statut (« maintenant » / « plus tard », suivi de « (hors quota) » si le quartier ne consomme pas d'emplacement de population). 
- **Légende**, dans une section repliable (« Légende », état mémorisé, clé `city_legend` de `collapsed`) :
  - les icônes des quartiers déjà construits sur la carte : icône et nom (`district_label`), **une seule fois par sorte** de quartier même s'il apparaît plusieurs fois, sur 2 colonnes. Le nom vient de préférence d'un quartier de la ville (ex. « Mbanza » plutôt que « Quartier résidentiel ») ;
  - une ligne d'aide qui rappelle les conventions (frontière, icônes cerclées ou estompées, cercles en tirets ou en points, losanges, hachures).
- Sans carte (avant le premier début de tour) : « Carte des villes disponible au début du prochain tour ».

### 4.5 Page Colonisation (`settle`)
- Placée entre Villes et Jalons dans l'ordre des onglets et de `Ctrl+Alt+P`.
- **Carte** de la zone découverte autour des villes et des colons (`settle.tiles`, même widget `HexMap`, 300 px de haut) :
  - territoire du joueur bordé de blanc, territoire étranger hachuré ;
  - villes du joueur cerclées, villes étrangères estompées ;
  - merveilles naturelles 🏞️ et ressources comme sur la page Villes ;
  - sites conseillés en cercles pointillés « n°1 » à « n°5 », le n°1 en doré.
- **Liste** : une ligne par site (« n°1 », score, raisons, « à N tuiles de <ville> »).
- Sans données (avant le premier début de tour avec le mod à jour) : « Carte de colonisation disponible au début du prochain tour ».

### 4.3 Page Jalons (`milestones`)
- Jalons passés (`status: "done"`) en gris, jalons à venir en surbrillance.
- Exemple : `Tour 1 · Capitale fondée` · `▶ Tour 32 · ≈ Recherche : Équitation`

### Retiré : bandeau (`snapshot`)
Retiré le 2026-10-29 : il répétait les informations de l'interface du jeu. Le moteur publie toujours `snapshot` (spec 04).

## 5. Robustesse
- Un message non conforme au schéma est logué et ignoré ; l'UI conserve le dernier état valide.
- Aucun appel réseau ni fichier dans le thread UI en dehors de `QtWebSockets` (asynchrone).

## 6. Tâches pour Claude Code
1. ✅ Squelette PySide6 : `src/ui/main.py`, `src/ui/overlay_window.py` (flags, modes, persistance), `src/ui/settings.py`.
2. ✅ `src/ui/hotkeys.py` (`RegisterHotKey` via `ctypes`, intégré avec `QAbstractNativeEventFilter`).
3. ✅ `src/ui/ws_client.py` (reconnexion, validation, signaux Qt).
4. ✅ `src/ui/styles/dark.qss`.
5. ✅ Pages : `src/ui/pages/` (actions, stratégies, jalons), liste d'actions réutilisable `src/ui/widgets/action_list.py`, section repliable `src/ui/panels/collapsible.py`.
6. ✅ Choix de stratégie, puis `EngineClient.follow_strategy` (spec 04 §4).
7. ✅ Tests hors écran : `tests/test_ui_pages.py` (bascule automatique, sections, bouton « Suivre »).

### Notes d'implémentation
- **Hauteur** : elle suit le contenu de la page affichée ; la largeur reste celle choisie par le joueur.
  - Elle est calculée avec `totalHeightForWidth`, car `sizeHint()` surestime les textes à retour à la ligne.
  - Les pages sont empilées dans un simple conteneur où les pages non affichées sont masquées : `QStackedWidget` réservait la hauteur de la plus grande page.
  - Un `addStretch` final absorbe l'éventuel surplus.
- **Données périmées** : on pose la propriété dynamique `stale` sur la racine (`QFrame#root[stale="true"] QLabel`), puis on réapplique le style. Les pseudo-états `:disabled` sur un ancêtre étaient mal évalués par Qt et grisaient tout en permanence (corrigé le 2026-10-29).
- Le seuil d'urgence (priorité ≥ 80) est le même que celui du moteur (spec 02 §6.5) ; il ne sert qu'à répartir les actions en sections.
