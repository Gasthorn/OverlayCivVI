"""Disposition des quartiers d'une ville (spec 02 §7).

Pour chaque ville, on cherche où placer les quartiers manquants, sur les tuiles des 3 premiers
anneaux (achetées ou non, hors tuiles d'une autre civilisation) :
- l'adjacence de base d'un quartier sur une tuile est celle calculée par le jeu (`plots[].sites`),
  sur la carte actuelle ;
- on y ajoute les interactions avec les quartiers **prévus** (ex. Port + Plateforme commerciale,
  Aqueduc + Zone industrielle, « +1 pour 2 quartiers voisins ») et le gain qu'un quartier prévu
  apporte aux quartiers déjà construits, d'après les règles de la base (`GameDb.district_interaction`) ;
- l'adjacence produite par le quartier de la stratégie suivie compte double (`FOCUS_WEIGHT`) :
  en cas de conflit pour une tuile, c'est lui qui l'obtient ;
- les tuiles portant un luxe, une ressource stratégique ou un site archéologique visibles sont
  exclues ; une ressource bonus (supprimée par le quartier) coûte `BONUS_RESOURCE_PENALTY`.

Recherche : placement glouton (meilleur gain pondéré d'abord), puis amélioration locale (déplacer
un quartier tant que le total pondéré augmente). Les coordonnées de dessin sont déduites des
voisins donnés par le jeu, sans hypothèse sur la convention de la grille.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from engine.game_db import WONDER_DISTRICT, GameDb
from engine.state import City, CityPlot, DistrictSite, GameState, SettleMap
from engine.strategy_focus import PLANS

if TYPE_CHECKING:
    from engine.wonders import WonderPick

# Ordre par défaut des quartiers, après celui de la stratégie suivie ; les quartiers de soutien
# (sans emplacement de population pour la plupart) viennent en dernier.
DEFAULT_PRIORITY = (
    "DISTRICT_CAMPUS", "DISTRICT_COMMERCIAL_HUB", "DISTRICT_HOLY_SITE", "DISTRICT_THEATER",
    "DISTRICT_INDUSTRIAL_ZONE", "DISTRICT_HARBOR", "DISTRICT_GOVERNMENT", "DISTRICT_ENCAMPMENT",
    "DISTRICT_DIPLOMATIC_QUARTER", "DISTRICT_PRESERVE", "DISTRICT_ENTERTAINMENT_COMPLEX",
    "DISTRICT_WATER_ENTERTAINMENT_COMPLEX", "DISTRICT_AQUEDUCT", "DISTRICT_DAM", "DISTRICT_NEIGHBORHOOD",
    "DISTRICT_AERODROME", "DISTRICT_SPACEPORT",
)
FOCUS_WEIGHT = 2.0
IMPROVEMENT_PASSES = 3
NOT_COUNTED = (None, "DISTRICT_WONDER")  # pas de bonus « quartier voisin » pour une merveille

# Ressources visibles : un quartier ne doit jamais écraser un luxe, une ressource stratégique ou
# un site archéologique ; poser un quartier sur une ressource bonus la supprime (léger malus).
RESOURCE_KINDS = {
    "RESOURCECLASS_LUXURY": "luxury",
    "RESOURCECLASS_STRATEGIC": "strategic",
    "RESOURCECLASS_ARTIFACT": "artifact",
    "RESOURCECLASS_BONUS": "bonus",
}
PROTECTED_RESOURCES = frozenset({"luxury", "strategic", "artifact"})
BONUS_RESOURCE_PENALTY = 0.5


def resource_kind(db: GameDb | None, resource: str | None) -> str | None:
    if resource is None:
        return None
    if db is None:
        return "bonus"
    return RESOURCE_KINDS.get(db.resource_class.get(resource, ""), "bonus")


def is_protected(plot: CityPlot, db: GameDb | None) -> bool:
    return resource_kind(db, plot.resource) in PROTECTED_RESOURCES


def resource_penalty(plot: CityPlot, db: GameDb | None) -> float:
    return BONUS_RESOURCE_PENALTY if resource_kind(db, plot.resource) == "bonus" else 0.0


def best_sites_from_plots(
    plots: tuple[CityPlot, ...], db: GameDb
) -> dict[str, DistrictSite]:
    """Meilleur emplacement par quartier, recalculé depuis la carte : hors tuiles étrangères et
    ressources protégées, une ressource bonus départageant à adjacence égale."""
    best: dict[str, tuple[float, CityPlot, float]] = {}
    for plot in plots:
        if plot.foreign or plot.other_city or plot.district is not None or is_protected(plot, db):
            continue
        for district, adjacency in plot.sites.items():
            score = adjacency - resource_penalty(plot, db)
            if district not in best or score > best[district][0]:
                best[district] = (score, plot, adjacency)
    return {d: DistrictSite(adjacency, p.hex_x, p.hex_y) for d, (_, p, adjacency) in best.items()}


@dataclass(frozen=True)
class Placement:
    district: str
    plot: int
    adjacency: float  # base (jeu) + interactions avec les autres quartiers prévus (non pondérée)


class CityPlotsCache:
    """Cartes détaillées et meilleurs emplacements : le mod ne les exporte qu'en début de tour."""

    def __init__(self) -> None:
        self._game_id: str | None = None
        self._plots: dict[int, tuple[CityPlot, ...]] = {}
        self._sites: dict[int, dict[str, DistrictSite]] = {}
        self._wonders: dict[int, dict[str, tuple[int, ...]]] = {}
        self._settle: SettleMap | None = None

    def update(
        self, game_id: str, state: GameState, db: GameDb | None = None
    ) -> dict[int, tuple[CityPlot, ...]]:
        if game_id != self._game_id:
            self._game_id, self._plots, self._sites, self._wonders = game_id, {}, {}, {}
            self._settle = None
        if state.settle_map is not None:
            self._settle = state.settle_map
        for city in state.cities:
            if city.wonder_sites is not None:
                self._wonders[city.city_id] = city.wonder_sites
            if city.plots is not None:
                self._plots[city.city_id] = city.plots
                if db is not None:
                    # Recalculés depuis la carte : le mod ignore les ressources à protéger.
                    self._sites[city.city_id] = best_sites_from_plots(city.plots, db)
                    continue
            if city.district_sites is not None:
                self._sites[city.city_id] = city.district_sites
        return {c.city_id: self._plots[c.city_id] for c in state.cities if c.city_id in self._plots}

    def enrich(self, state: GameState) -> GameState:
        """Remplace `district_sites` par la dernière version connue (calculée depuis la carte quand
        elle existe ; reprise du début de tour pour les autres déclencheurs), et reporte la carte
        et les emplacements de merveilles du début de tour (choix des merveilles, `wonders.py`)."""
        def enriched(c: City) -> City:
            changes: dict[str, Any] = {}
            if c.city_id in self._sites:
                changes["district_sites"] = self._sites[c.city_id]
            if c.plots is None and c.city_id in self._plots:
                changes["plots"] = self._plots[c.city_id]
            if c.wonder_sites is None and c.city_id in self._wonders:
                changes["wonder_sites"] = self._wonders[c.city_id]
            return replace(c, **changes) if changes else c

        settle = state.settle_map or self._settle
        if settle is not None:
            # Convention de grille déduite des voisins donnés par le jeu (cartes de villes).
            plots = next(iter(self._plots.values()), None)
            settle = replace(settle, odd_shifted=odd_rows_shifted(plots) if plots else True)
        return replace(state, cities=tuple(enriched(c) for c in state.cities), settle_map=settle)


# --- Évaluation -------------------------------------------------------------------

class _Evaluator:
    def __init__(
        self, plots: tuple[CityPlot, ...], db: GameDb, state: GameState, weights: dict[str, float],
        reserved: dict[int, str] | None = None,
    ) -> None:
        self.db = db
        self.by_index = {p.index: p for p in plots}
        # Tuiles réservées hors quartiers (merveille prévue) : voisines comptées, jamais occupées.
        self.reserved = reserved or {}
        self.traits = db.player_traits(state.civilization, state.leader)
        self.researched = set(state.researched)
        self.civics = set(state.civics_unlocked or ())
        self._weights = weights
        self._cache: dict[tuple[str, str], float] = {}

    def weight(self, district: str) -> float:
        return self._weights.get(self.db.generic_district(district), 1.0)

    def interaction(self, district: str, neighbor: str) -> float:
        key = (district, neighbor)
        if key not in self._cache:
            self._cache[key] = self.db.district_interaction(
                district, neighbor, self.traits, self.researched, self.civics
            )
        return self._cache[key]

    def neighbors(self, plot: int) -> list[CityPlot]:
        return [self.by_index[n] for n in self.by_index[plot].neighbors if n in self.by_index]

    def own_adjacency(self, district: str, plot: int, placed: dict[int, str]) -> float:
        """Adjacence du quartier lui-même : base du jeu + quartiers prévus voisins."""
        total = self.by_index[plot].sites[district]
        for neighbor in self.neighbors(plot):
            other = placed.get(neighbor.index) or self.reserved.get(neighbor.index)
            if other is not None:
                total += self.interaction(district, other)
        return total

    def penalty(self, plot: int) -> float:
        return resource_penalty(self.by_index[plot], self.db)

    def gain(self, district: str, plot: int, placed: dict[int, str]) -> float:
        """Gain pondéré si `district` est posé sur `plot`, les quartiers `placed` étant déjà prévus."""
        total = self.weight(district) * self.own_adjacency(district, plot, placed) - self.penalty(plot)
        for neighbor in self.neighbors(plot):
            other = placed.get(neighbor.index) or neighbor.district
            if other not in NOT_COUNTED:
                # Le voisin (prévu ou déjà construit) profite aussi du nouveau quartier.
                total += self.weight(other) * self.interaction(other, district)
        return total

    def layout_value(self, placed: dict[int, str]) -> float:
        value = 0.0
        for plot, district in placed.items():
            others = {p: d for p, d in placed.items() if p != plot}
            value += self.weight(district) * self.own_adjacency(district, plot, others) - self.penalty(plot)
            for neighbor in self.neighbors(plot):
                if neighbor.index not in placed and neighbor.district not in NOT_COUNTED:
                    value += self.weight(neighbor.district) * self.interaction(neighbor.district, district)
        return value


def strategy_weights(followed: str | None) -> dict[str, float]:
    """Poids par quartier générique : le quartier de la stratégie suivie compte double."""
    plan = PLANS.get(followed or "")
    return {plan.district: FOCUS_WEIGHT} if plan and plan.district else {}


def excluded_districts(city: City, state: GameState, db: GameDb) -> set[str]:
    """Quartiers génériques à ne pas proposer dans `city` : limite par empire atteinte, ou pas la
    capitale (la Place du gouvernement et le Quartier diplomatique y sont proposés), et quartiers
    exclusifs d'un quartier déjà construit dans la ville."""
    excluded = set()
    for district, maximum in db.district_max_per_player.items():
        variants = db.variants(db.generic_district(district))
        built = sum(1 for c in state.cities for d in c.districts if d in variants)
        if built >= maximum or not city.is_capital:
            excluded.add(db.generic_district(district))
    for district in city.districts:
        excluded.update(db.generic_district(d) for d in db.exclusive_districts.get(district, ()))
    return excluded


def plan_layout(
    plots: tuple[CityPlot, ...],
    db: GameDb,
    state: GameState,
    weights: dict[str, float] | None = None,
    excluded: set[str] | None = None,
    reserved: dict[int, str] | None = None,
) -> list[Placement]:
    """Meilleure disposition trouvée pour les quartiers que la ville peut encore accueillir, débloqués
    ou non : la place des quartiers futurs est réservée dès maintenant. `reserved` : tuiles déjà
    promises (merveille prévue -> DISTRICT_WONDER), laissées libres mais comptées comme voisines."""
    ev = _Evaluator(plots, db, state, weights or {}, reserved)
    # Le jeu déclare valides des emplacements pour les quartiers uniques d'autres civilisations :
    # on ne garde, par type générique, que la version que le joueur peut construire.
    candidates = {d for p in plots if not p.foreign for d in p.sites}
    buildable = {
        d for d in candidates
        if db.resolve_for_player(db.generic_district(d), ev.traits) == d
        and db.generic_district(d) not in (excluded or ())
    }
    free = {
        p.index for p in plots
        if not p.foreign and not p.other_city and p.district is None and not is_protected(p, db)
        and p.index not in ev.reserved and buildable & p.sites.keys()
    }
    remaining = sorted(buildable)
    placed: dict[int, str] = {}

    # 1. Glouton : à chaque étape, le placement au meilleur gain pondéré.
    while remaining:
        best: tuple[float, str, int] | None = None
        for district in remaining:
            for plot in free - placed.keys():
                if district in ev.by_index[plot].sites:
                    gain = ev.gain(district, plot, placed)
                    if best is None or (gain, district, -plot) > (best[0], best[1], -best[2]):
                        best = (gain, district, plot)
        if best is None:
            break
        _, district, plot = best
        placed[plot] = district
        remaining.remove(district)
        # Un seul des quartiers exclusifs (Complexe de divertissement / Parc aquatique) : le meilleur.
        remaining = [d for d in remaining if d not in db.exclusive_districts.get(district, ())]

    # 2. Amélioration locale : déplacer un quartier si le total pondéré augmente.
    for _ in range(IMPROVEMENT_PASSES):
        improved = False
        for plot, district in list(placed.items()):
            current = ev.layout_value(placed)
            for target in sorted(free - placed.keys()):
                if district not in ev.by_index[target].sites:
                    continue
                candidate = {p: d for p, d in placed.items() if p != plot} | {target: district}
                if ev.layout_value(candidate) > current + 1e-9:
                    placed, current, improved = candidate, ev.layout_value(candidate), True
                    break
        if not improved:
            break

    return [
        Placement(district, plot, ev.own_adjacency(district, plot, {p: d for p, d in placed.items() if p != plot}))
        for plot, district in placed.items()
    ]


# --- Grille de dessin ------------------------------------------------------------------

def odd_rows_shifted(plots: tuple[CityPlot, ...]) -> bool:
    """Déduit des voisins donnés par le jeu quelles rangées sont décalées d'un demi-hexagone (à droite).

    Une tuile d'une rangée décalée a ses voisins de la rangée suivante en {x, x+1} ; une tuile
    d'une rangée non décalée les a en {x-1, x}.
    """
    by_index = {p.index: p for p in plots}
    for plot in plots:
        for n in plot.neighbors:
            other = by_index.get(n)
            if other is None or other.hex_y != plot.hex_y + 1 or abs(other.hex_x - plot.hex_x) > 1:
                continue  # autre rangée, ou bord de carte qui boucle
            if other.hex_x == plot.hex_x + 1:
                return plot.hex_y % 2 == 1  # la rangée de `plot` est décalée
            if other.hex_x == plot.hex_x - 1:
                return plot.hex_y % 2 == 0  # la rangée de `plot` ne l'est pas
    return True


def draw_position(plot: CityPlot, odd_shifted: bool) -> tuple[float, float]:
    shifted = (plot.hex_y % 2 == 1) == odd_shifted
    return plot.hex_x + (0.5 if shifted else 0.0), float(plot.hex_y)


# --- Messages (spec 04 §3, `cities`) ------------------------------------------------------

def city_layouts(
    state: GameState, db: GameDb, plots_by_city: dict[int, tuple[CityPlot, ...]], followed: str | None
) -> list[dict[str, Any]]:
    from engine.wonders import wonder_pick  # import tardif : wonders.py importe ce module

    weights = strategy_weights(followed)
    focus = next(iter(weights), None)
    priority = ((focus,) if focus else ()) + tuple(d for d in DEFAULT_PRIORITY if d != focus)
    pick = wonder_pick(state, db, followed)
    return [
        _city_message(
            city, plots_by_city[city.city_id], db, state, weights, priority, focus,
            pick if pick is not None and pick.city_id == city.city_id and pick.plot is not None else None,
        )
        for city in state.cities
        if city.city_id in plots_by_city
    ]


def _city_message(
    city: City,
    plots: tuple[CityPlot, ...],
    db: GameDb,
    state: GameState,
    weights: dict[str, float],
    priority: tuple[str, ...],
    focus: str | None,
    wonder: WonderPick | None = None,
) -> dict[str, Any]:
    by_index = {p.index: p for p in plots}
    odd_shifted = odd_rows_shifted(plots)
    reserved = {wonder.plot.index: WONDER_DISTRICT} if wonder is not None and wonder.plot.index in by_index else {}
    placements = plan_layout(plots, db, state, weights, excluded_districts(city, state, db), reserved)
    researched, civics = set(state.researched), set(state.civics_unlocked or ())
    missing = {p.district: db.missing_prereq(p.district, researched, civics) for p in placements}

    def rank(placement: Placement) -> tuple[bool, int, float]:
        generic = db.generic_district(placement.district)
        order = priority.index(generic) if generic in priority else len(priority)
        return missing[placement.district] is not None, order, -placement.adjacency

    placements.sort(key=rank)
    free_slots = (
        max(0, city.district_slots.allowed - city.district_slots.used)
        if city.district_slots is not None else len(placements)
    )

    tiles = []
    for plot in plots:
        x, y = draw_position(plot, odd_shifted)
        tiles.append({
            "x": x, "y": y, "hex_x": plot.hex_x, "hex_y": plot.hex_y,
            "terrain": plot.terrain, "feature": plot.feature, "resource": plot.resource,
            "resource_kind": resource_kind(db, plot.resource),
            "improvement": plot.improvement,
            "district": db.generic_district(plot.district) if plot.district else None,
            "district_label": db.name(plot.district) if plot.district else None,
            "river": plot.river, "owned": plot.owned, "foreign": plot.foreign,
            "other_city": plot.other_city,
        })

    layout = []
    if reserved:
        # Merveille de la stratégie en tête : adjacence = bonus apporté aux quartiers voisins, existants
        # ou prévus (ex. Place du théâtre +2 avec BBG).
        traits = db.player_traits(state.civilization, state.leader)
        planned = {p.plot: p.district for p in placements}
        bonus = sum(
            db.district_interaction(neighbor, WONDER_DISTRICT, traits, researched, civics)
            for n in wonder.plot.neighbors
            if (neighbor := planned.get(n) or (by_index[n].district if n in by_index else None))
            not in NOT_COUNTED
        )
        layout.append({
            "district": wonder.wonder, "kind": WONDER_DISTRICT, "label": db.name(wonder.wonder),
            "hex_x": wonder.plot.hex_x, "hex_y": wonder.plot.hex_y, "adjacency": round(bonus, 1),
            "status": "now", "uses_slot": False, "focus": True, "unlocked": True, "requires": None,
            "wonder": True,
        })
    for placement in placements:
        plot = by_index[placement.plot]
        generic = db.generic_district(placement.district)
        uses_slot = db.district_requires_population.get(placement.district, True)
        requires = missing[placement.district]
        if requires is not None:
            status = "later"  # pas encore débloqué : emplacement réservé
        elif uses_slot:
            status = "now" if free_slots > 0 else "later"
            free_slots -= 1
        else:
            status = "now"  # Aqueduc, Barrage, Quartier résidentiel… : hors quota de population
        layout.append({
            "district": placement.district,
            "kind": generic,
            "label": db.name(placement.district),
            "hex_x": plot.hex_x,
            "hex_y": plot.hex_y,
            "adjacency": round(placement.adjacency, 1),
            "status": status,
            "uses_slot": uses_slot,
            "focus": generic == focus,
            "unlocked": requires is None,
            "requires": db.name(requires) if requires is not None else None,
        })

    return {
        "city_id": city.city_id,
        "name": city.name,
        "population": city.population,
        "slots": None if city.district_slots is None else {
            "used": city.district_slots.used, "allowed": city.district_slots.allowed,
        },
        "tiles": tiles,
        "layout": layout,
    }
