# Spec 04 : Contrat Moteur ↔ Overlay

## 1. Transport
- WebSocket, serveur dans le service moteur, sur `ws://127.0.0.1:8765` (écoute **uniquement** sur localhost ; port modifiable par configuration).
- Messages JSON texte, un objet par trame. Chaque message contient `type` et `schema_version` (2 pour les messages du serveur, 1 pour ceux du client).
- À la connexion d'un client, le serveur renvoie immédiatement le dernier `status` et le dernier `recommendations` connus (s'il y en a).
- Le serveur publie `status` et `recommendations` (§2, §3). Le client peut envoyer des commandes (§4).

Schémas formels, qui font foi :
- du serveur vers le client : `specs/schemas/recommendations.schema.json` ;
- du client vers le serveur : `specs/schemas/client_messages.schema.json`.

## 2. Message `status`
Publié au démarrage, à chaque changement d'état et à chaque `game_state` reçu.

```json
{
  "type": "status",
  "schema_version": 2,
  "state": "ok",
  "turn": 12,
  "game_id": "LEADER_TRAJAN_1849302",
  "detail": null
}
```

| `state` | Signification |
|---|---|
| `waiting_for_game` | Aucun `game_state` reçu depuis le démarrage |
| `ok` | Fonctionnement normal |
| `degraded` | Base de données du jeu absente ou autre fonction partielle ; `detail` en donne la raison |

## 3. Message `recommendations`
Les listes sont recalculées après chaque `game_state` de type `game_loaded`, `turn_begin` ou `state_changed`, et après chaque changement de stratégie suivie (§4). Pour `turn_end`, seul `snapshot` est mis à jour.

```json
{
  "type": "recommendations",
  "schema_version": 2,
  "game_id": "LEADER_TRAJAN_1849302",
  "turn": 12,
  "generated_at": "2026-10-29T20:15:03Z",
  "followed_strategy": "cavalry_rush",
  "snapshot": {
    "era": "ERA_ANCIENT",
    "gold": 45.2,
    "gold_per_turn": 8.5,
    "science_per_turn": 12.1,
    "culture_per_turn": 9.4,
    "faith": 10.0
  },
  "strategies": [
    {
      "id": "cavalry_rush",
      "label": "Rush Cavalerie",
      "icon": "horse",
      "score": 0.82,
      "factors": ["2 chevaux visibles près de Rome", "Équitation boostée"]
    }
  ],
  "actions": [
    {
      "id": "boosted_available:TECH_HORSEBACK_RIDING",
      "category": "research",
      "title": "Rechercher Équitation",
      "reason": "Boost Eureka déjà obtenu : 50 % du coût économisé",
      "priority": 80,
      "source": "rules",
      "target": { "type": "TECH_HORSEBACK_RIDING", "city_id": null, "unit_id": null }
    }
  ]
}
```

### Champs
- `followed_strategy` : id de la stratégie suivie pour cette partie, ou `null`.
- `snapshot` : n'est plus affiché par l'overlay (spec 03, panel 0 retiré), mais reste publié pour d'autres usages (conseiller LLM, outils).
- `milestones` : retiré en version 2 (2026-11-02), avec la page Jalons de l'overlay.
- `strategies[].score` : nombre dans `[0.0, 1.0]`. `icon` est un identifiant d'icône parmi `horse`, `coin`, `flask`, `scroll`, `shield`, `dove`, `anchor`.
- `actions[].category` : `research` | `civic` | `production` | `unit` | `policy` | `other`.
- `actions[].priority` : entier entre 0 et 100 (100 = le plus urgent).
- `actions[].source` : `rules` | `llm`.
- `actions[].id` : stable d'un tour à l'autre pour la même recommandation (`<rule_id>:<cible>`). L'UI peut ainsi animer les apparitions et disparitions.
- `actions[].target` : facultatif ; les sous-champs inutiles valent `null`.
- `actions[].strategy` : facultatif ; id de la stratégie que sert l'action (actions de focus, spec 02 §6.5).
- `cities[]` : carte et disposition conseillée de chaque ville dont la carte est connue (spec 02 §7). Liste vide avant le premier début de tour.
  - `city_id`, `name`, `population`, et `slots` (`{used, allowed}` ou `null`).
  - `tiles[]` : `x`, `y` (position de dessin en unités d'hexagone, rangées décalées appliquées, nord en haut), `hex_x`, `hex_y`, `terrain`, `feature`, `resource`, `resource_kind` (`luxury` | `strategic` | `artifact` | `bonus` | `null`), `improvement`, `district` (type **générique**), `district_label` (nom affiché du quartier réel, ex. « Mbanza »), `river`, `owned` (achetée), `foreign` (autre civilisation), `other_city` (nom de l'autre ville du joueur qui possède la tuile, ou `null`).
  - `layout[]` : quartiers à placer, dans l'ordre conseillé, avec :
    - `district` (type réel, éventuellement unique), `kind` (type générique, pour l'icône), `label` (nom affiché) ;
    - `hex_x`, `hex_y`, `adjacency` (adjacence prévue, interactions comprises) ;
    - `status` (`now` | `later`), `uses_slot` (consomme un emplacement de population) et `focus` (quartier de la stratégie suivie) ;
    - `unlocked` (prérequis acquis) et `requires` (nom de la technologie ou du dogme manquant, `null` si débloqué). Un quartier verrouillé est toujours `later` ;
    - `wonder: true` pour la merveille de la stratégie suivie (spec 02 §6.7) : `district` est alors le type de la merveille (`BUILDING_…`), `kind` vaut `DISTRICT_WONDER` et `adjacency` le bonus apporté aux quartiers voisins. Elle vient en tête de `layout`.

- `settle` : carte et sites de colonisation (spec 02 §9), ou `null` avant le premier début de tour.
  - `tiles[]` : mêmes champs que `cities[].tiles` (`x`, `y`, `hex_x`, `hex_y`, `terrain`, `feature`, `resource`, `resource_kind`, `district`, `river`, `owned`, `foreign`), plus `natural_wonder`. `district` vaut `DISTRICT_CITY_CENTER` pour une ville, du joueur (`owned`) ou étrangère (`foreign`).
  - `sites[]` : `rank` (1 = meilleur), `hex_x`, `hex_y`, `score`, `reasons` (textes, les plus marquants d'abord), `nearest_city` et `distance` (ville du joueur la plus proche, ou `null`).

## 4. Messages du client

### `follow_strategy`
Suivre une stratégie pour la partie en cours (`strategy_id` est l'id d'une stratégie de `strategies[]`), ou arrêter de suivre (`null`).

```json
{ "type": "follow_strategy", "schema_version": 1, "strategy_id": "science_campus" }
```

- Le serveur mémorise le choix par `game_id`, de façon persistante, puis republie aussitôt `recommendations`, recalculé avec le nouveau `followed_strategy`.
- Un id inconnu, ou un choix fait alors qu'aucune partie n'est en cours, est logué et ignoré.
- Un message non conforme au schéma est logué et ignoré ; la connexion reste ouverte.
