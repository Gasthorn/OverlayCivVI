"""Sites de colonisation sur la partie découverte de la carte (spec 02 §9).

Entrée : `settle_map` (spec 01), les tuiles révélées autour des villes et des colons du joueur.
Un site candidat est une tuile de terre où le jeu autorise une ville : ni eau, ni montagne, ni
merveille naturelle, ni territoire étranger, à au moins 4 tuiles de toute ville connue. Son score
additionne des facteurs lisibles (eau douce, ressources, colline, merveille naturelle, distance aux
villes du joueur et aux villes étrangères, chevauchement), affichés comme raisons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.game_db import GameDb
from engine.state import GameState, SettleMap, SettleTile
from engine.text import plural

MIN_CITY_DISTANCE = 4    # Civ VI : 3 tuiles au moins entre deux centres-villes
MAX_OWN_DISTANCE = 6     # au-delà, la ville est isolée (loyauté, défense)
WORK_RADIUS = 3
NEAR_RADIUS = 2          # tuiles exploitées tôt : poids plein ; 3e anneau : RING3_WEIGHT
RING3_WEIGHT = 0.6
MAX_CANDIDATES = 5

FRESH_WATER = 4.0
COAST = 2.0
NO_WATER = -1.0
HILLS = 1.5
LUXURY = 2.0
NEW_LUXURY = 1.0
STRATEGIC = 1.5
DUPLICATE_SHARE = 0.25   # exemplaire supplémentaire d'une même ressource
BONUS = 0.7
NATURAL_WONDER = 2.0
GOOD_TERRAIN = 0.15      # par tuile de prairie, plaine, colline, montagne (adjacences), 2 anneaux
POOR_TERRAIN = -0.2      # par tuile de désert, toundra, neige
OVERLAP = -0.4           # tuile déjà à une ville du joueur
FOREIGN_TILE = -0.5
FOREIGN_CITY_CLOSE = -3.0  # ville étrangère à 5 tuiles ou moins
FOREIGN_CITY_NEAR = -1.0   # à 6 ou 7 tuiles
COMPACT = 1.0            # à 4 ou 5 tuiles d'une ville du joueur

WATER_TERRAINS = {"TERRAIN_COAST", "TERRAIN_OCEAN"}
GOOD_TERRAINS = {"TERRAIN_GRASS", "TERRAIN_PLAINS"}
POOR_TERRAINS = {"TERRAIN_DESERT", "TERRAIN_TUNDRA", "TERRAIN_SNOW"}
FRESH_WATER_FEATURES = {"FEATURE_OASIS"}


class HexGrid:
    """Grille à rangées décalées (convention déduite des voisins donnés par le jeu, spec 02 §7),
    qui boucle d'est en ouest."""

    def __init__(self, width: int, height: int, odd_shifted: bool = True) -> None:
        self.width, self.height, self.odd_shifted = width, height, odd_shifted

    def _shifted(self, y: int) -> bool:
        return (y % 2 == 1) == self.odd_shifted

    def neighbors(self, x: int, y: int) -> list[tuple[int, int]]:
        dx = (0, 1) if self._shifted(y) else (-1, 0)
        coords = [
            (x - 1, y), (x + 1, y),
            (x + dx[0], y - 1), (x + dx[1], y - 1),
            (x + dx[0], y + 1), (x + dx[1], y + 1),
        ]
        return [(cx % self.width, cy) for cx, cy in coords if 0 <= cy < self.height]

    def _axial(self, x: int, y: int) -> tuple[int, int]:
        """Coordonnées axiales (q, r) : chaque rangée décalée avance d'un demi-hexagone vers l'est."""
        return x - (y // 2 if self.odd_shifted else (y + 1) // 2), y

    def distance(self, a: tuple[int, int], b: tuple[int, int]) -> int:
        best = None
        for shift in (-self.width, 0, self.width):
            q1, r1 = self._axial(*a)
            q2, r2 = self._axial(b[0] + shift, b[1])
            dq, dr = q2 - q1, r2 - r1
            d = (abs(dq) + abs(dr) + abs(dq + dr)) // 2
            best = d if best is None else min(best, d)
        return best

    def within(self, xy: tuple[int, int], radius: int) -> dict[tuple[int, int], int]:
        """Tuiles à `radius` ou moins de `xy`, avec leur distance (parcours en largeur)."""
        found = {xy: 0}
        frontier = [xy]
        for d in range(1, radius + 1):
            frontier = [n for c in frontier for n in self.neighbors(*c) if n not in found]
            for n in frontier:
                found.setdefault(n, d)
            frontier = list(dict.fromkeys(frontier))
        return found

    def unwrap(self, x: int, reference: int) -> int:
        """Abscisse la plus proche de `reference` (carte qui boucle), pour dessiner d'un seul tenant."""
        return min((x + k * self.width for k in (-1, 0, 1)), key=lambda v: abs(v - reference))

    def draw_position(self, x: int, y: int, reference: int) -> tuple[float, float]:
        return self.unwrap(x, reference) + (0.5 if self._shifted(y) else 0.0), float(y)


@dataclass
class SettleSite:
    hex_x: int
    hex_y: int
    score: float
    factors: list[tuple[float, str]] = field(default_factory=list)  # (poids, texte)
    nearest_city: str | None = None
    distance: int | None = None

    def reasons(self, limit: int = 4) -> list[str]:
        """Facteurs les plus marquants, positifs d'abord."""
        ordered = sorted(self.factors, key=lambda f: (f[0] < 0, -abs(f[0])))
        return [text for _, text in ordered[:limit]]


def is_water(tile: SettleTile) -> bool:
    return tile.terrain in WATER_TERRAINS


def is_mountain(tile: SettleTile) -> bool:
    return tile.terrain.endswith("_MOUNTAIN")


def _resource_class(db: GameDb | None, resource: str) -> str:
    return (db.resource_class.get(resource, "") if db is not None else "") or "RESOURCECLASS_BONUS"


def settle_sites(state: GameState, db: GameDb | None, limit: int = MAX_CANDIDATES) -> list[SettleSite]:
    settle = state.settle_map
    if settle is None:
        return []
    grid = HexGrid(settle.map_width, settle.map_height, settle.odd_shifted)
    tiles = {(t.hex_x, t.hex_y): t for t in settle.tiles}
    own_cities = {(c.hex_x, c.hex_y): c.name for c in state.cities}
    foreign_cities = [xy for xy, t in tiles.items() if t.city == "other"]
    all_cities = list(own_cities) + foreign_cities + [xy for xy, t in tiles.items() if t.city == "self"]
    owned_luxuries = {
        t.resource for t in state.tiles
        if t.owner == "self" and t.resource and _resource_class(db, t.resource) == "RESOURCECLASS_LUXURY"
    }

    sites = []
    for xy, tile in tiles.items():
        if is_water(tile) or is_mountain(tile) or tile.natural_wonder or tile.city or tile.owner == "other":
            continue
        if any(grid.distance(xy, c) < MIN_CITY_DISTANCE for c in all_cities):
            continue
        nearest = min(own_cities, key=lambda c: grid.distance(xy, c), default=None)
        distance = grid.distance(xy, nearest) if nearest is not None else None
        if distance is not None and distance > MAX_OWN_DISTANCE:
            continue
        site = SettleSite(xy[0], xy[1], 0.0, nearest_city=own_cities.get(nearest), distance=distance)
        _score(site, xy, tile, tiles, grid, db, foreign_cities, owned_luxuries)
        sites.append(site)

    # Meilleurs sites, assez éloignés entre eux pour pouvoir tous être fondés.
    chosen: list[SettleSite] = []
    for site in sorted(sites, key=lambda s: (-s.score, s.hex_y, s.hex_x)):
        if all(grid.distance((site.hex_x, site.hex_y), (c.hex_x, c.hex_y)) >= MIN_CITY_DISTANCE for c in chosen):
            chosen.append(site)
            if len(chosen) == limit:
                break
    return chosen


def _score(
    site: SettleSite, xy: tuple[int, int], tile: SettleTile, tiles: dict[tuple[int, int], SettleTile],
    grid: HexGrid, db: GameDb | None, foreign_cities: list[tuple[int, int]], owned_luxuries: set[str],
) -> None:
    def add(weight: float, text: str) -> None:
        if weight:
            site.factors.append((weight, text))
            site.score += weight

    neighbors = [tiles[n] for n in grid.neighbors(*xy) if n in tiles]
    if tile.river or any(n.lake or n.feature in FRESH_WATER_FEATURES for n in neighbors):
        add(FRESH_WATER, "eau douce (rivière, lac ou oasis)")
    elif any(is_water(n) and not n.lake for n in neighbors):
        add(COAST, "sur la côte (port, logement)")
    else:
        add(NO_WATER, "sans eau douce ni côte")
    if tile.terrain.endswith("_HILLS"):
        add(HILLS, "sur une colline (défense, production)")

    luxuries, new_luxuries, strategic, bonus, terrain = [], set(), [], 0.0, 0.0
    natural_wonder = False
    overlap = foreign = 0
    for other_xy, d in grid.within(xy, WORK_RADIUS).items():
        other = tiles.get(other_xy)
        if d == 0 or other is None:
            continue  # tuile non révélée : ni bonus ni malus
        weight = 1.0 if d <= NEAR_RADIUS else RING3_WEIGHT
        natural_wonder |= other.natural_wonder
        if other.owner == "self":
            overlap += 1
        elif other.owner == "other":
            foreign += 1
        if other.resource and other.owner != "other":
            kind = _resource_class(db, other.resource)
            name = db.name(other.resource) if db is not None else other.resource
            if kind == "RESOURCECLASS_LUXURY":
                luxuries.append((weight, name))
                if other.resource not in owned_luxuries:
                    new_luxuries.add(name)
            elif kind == "RESOURCECLASS_STRATEGIC":
                strategic.append((weight, name))
            elif kind == "RESOURCECLASS_BONUS":
                bonus += BONUS * weight
        if d <= NEAR_RADIUS:
            base = other.terrain.removesuffix("_HILLS")
            if base in GOOD_TERRAINS or is_mountain(other):
                terrain += GOOD_TERRAIN
            elif base in POOR_TERRAINS and other.feature != "FEATURE_FLOODPLAINS":
                terrain += POOR_TERRAIN

    if luxuries:
        names = sorted({n for _, n in luxuries})
        add(_by_kind(luxuries, LUXURY), f"{plural(len(names), 'luxe')} ({', '.join(names)})")
    if new_luxuries:
        add(NEW_LUXURY * len(new_luxuries), f"nouveau luxe pour l'empire ({', '.join(sorted(new_luxuries))})")
    if strategic:
        names = sorted({n for _, n in strategic})
        add(_by_kind(strategic, STRATEGIC), f"ressource stratégique ({', '.join(names)})")
    if bonus:
        add(round(bonus, 1), "ressources bonus")
    if natural_wonder:
        add(NATURAL_WONDER, "merveille naturelle à proximité")
    add(round(terrain, 1), "bonnes terres" if terrain > 0 else "terres pauvres")
    if overlap:
        add(OVERLAP * overlap, f"chevauche le territoire de vos villes ({plural(overlap, 'tuile')})")
    if foreign:
        add(FOREIGN_TILE * foreign, f"touche un territoire étranger ({plural(foreign, 'tuile')})")
    if foreign_cities:
        closest = min(grid.distance(xy, c) for c in foreign_cities)
        if closest <= 5:
            add(FOREIGN_CITY_CLOSE, f"ville étrangère à {closest} tuiles (loyauté, frontière)")
        elif closest <= 7:
            add(FOREIGN_CITY_NEAR, f"ville étrangère à {closest} tuiles")
    if site.distance is not None and site.distance <= 5:
        add(COMPACT, f"à {site.distance} tuiles de {site.nearest_city} (empire compact)")
    site.score = round(site.score, 1)


def _by_kind(found: list[tuple[float, str]], value: float) -> float:
    """Chaque sorte compte une fois en plein (un luxe ne donne qu'une commodité, quel que soit le
    nombre d'exemplaires) ; les exemplaires suivants valent DUPLICATE_SHARE (échanges, rendements)."""
    total, seen = 0.0, set()
    for weight, name in sorted(found, reverse=True):
        total += value * weight * (1.0 if name not in seen else DUPLICATE_SHARE)
        seen.add(name)
    return round(total, 1)


def settle_message(state: GameState, db: GameDb | None) -> dict[str, Any] | None:
    """Carte et sites conseillés pour la page Colonisation (spec 04, `settle`)."""
    from engine.city_layout import resource_kind

    settle = state.settle_map
    if settle is None:
        return None
    grid = HexGrid(settle.map_width, settle.map_height, settle.odd_shifted)
    reference = state.cities[0].hex_x if state.cities else settle.tiles[0].hex_x if settle.tiles else 0
    tiles = []
    for t in settle.tiles:
        x, y = grid.draw_position(t.hex_x, t.hex_y, reference)
        tiles.append({
            "x": x, "y": y, "hex_x": t.hex_x, "hex_y": t.hex_y, "terrain": t.terrain, "feature": t.feature,
            "resource": t.resource, "resource_kind": resource_kind(db, t.resource), "improvement": None,
            "district": "DISTRICT_CITY_CENTER" if t.city else None,
            "district_label": None, "river": t.river, "owned": t.owner == "self", "foreign": t.owner == "other",
            "other_city": None, "natural_wonder": t.natural_wonder,
        })
    sites = settle_sites(state, db)
    return {
        "tiles": tiles,
        "sites": [
            {
                "rank": rank, "hex_x": s.hex_x, "hex_y": s.hex_y, "score": s.score, "reasons": s.reasons(),
                "nearest_city": s.nearest_city, "distance": s.distance,
            }
            for rank, s in enumerate(sites, start=1)
        ],
    }
