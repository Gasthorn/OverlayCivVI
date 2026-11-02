"""Merveilles de la stratégie suivie : laquelle lancer, dans quelle ville, sur quelle tuile (spec 02 §6.7).

Le mod exporte, pour chaque ville, les merveilles qu'elle peut lancer maintenant (prérequis acquis,
pas encore construites ailleurs) et les tuiles où le jeu autorise à les placer (`wonder_sites`).
On retient la première merveille du plan (`PLANS[...].wonders`) disponible, puis la tuile qui :
- donne le plus de bonus aux quartiers voisins, existants (« merveille voisine », ex. Place du
  théâtre +2 avec BBG) ;
- sacrifie le moins de potentiel de quartier (meilleure adjacence de quartier de la tuile) et de
  ressource bonus ;
et la ville la plus peuplée à valeur proche (la population sert d'indicateur de production).
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.city_layout import resource_penalty
from engine.game_db import WONDER_DISTRICT, GameDb
from engine.state import CityPlot, GameState
from engine.strategy_focus import PLANS

POPULATION_WEIGHT = 0.5    # production estimée par la population
DISTRICT_POTENTIAL_WEIGHT = 0.5  # adjacence de quartier perdue sur la tuile de la merveille

# Pourquoi la merveille sert la stratégie (raison affichée).
WONDER_NOTES = {
    "BUILDING_STONEHENGE": "Grand Prophète gratuit : fonde une religion très tôt",
    "BUILDING_MAHABODHI_TEMPLE": "2 apôtres gratuits",
    "BUILDING_HAGIA_SOPHIA": "missionnaires et apôtres : +1 propagation",
    "BUILDING_ORACLE": "grands personnages patronnés moins chers",
    "BUILDING_GREAT_LIBRARY": "boosts des technologies antiques et classiques",
    "BUILDING_OXFORD_UNIVERSITY": "2 technologies gratuites",
    "BUILDING_COLOSSEUM": "culture et commodités autour de la ville",
    "BUILDING_FORBIDDEN_CITY": "emplacement de doctrine joker",
    "BUILDING_TERRACOTTA_ARMY": "promotion pour toutes les unités terrestres",
    "BUILDING_COLOSSUS": "+1 route commerciale",
    "BUILDING_PETRA": "bonus sur les tuiles de désert",
    "BUILDING_BIG_BEN": "double le trésor",
    "BUILDING_GREAT_LIGHTHOUSE": "+1 déplacement des unités navales et points de Grand Amiral",
    "BUILDING_VENETIAN_ARSENAL": "chaque navire de guerre produit l'est en double",
}


@dataclass(frozen=True)
class WonderPick:
    wonder: str
    city_id: int
    plot: CityPlot | None  # None : emplacements inconnus (état antérieur au champ)
    neighbor_bonus: float  # adjacence apportée aux quartiers voisins existants


def wonder_pick(state: GameState, db: GameDb, followed: str | None) -> WonderPick | None:
    plan = PLANS.get(followed or "")
    if plan is None or not plan.wonders or not state.cities:
        return None
    traits = db.player_traits(state.civilization, state.leader)
    researched, civics = set(state.researched), set(state.civics_unlocked or ())
    built = set().union(*(c.buildings for c in state.cities))
    producing = {c.current_production for c in state.cities}
    known = any(c.wonder_sites is not None for c in state.cities)

    for wonder in plan.wonders:
        if wonder in built:
            continue
        if wonder in producing:
            return None  # une merveille du plan est déjà en chantier : une à la fois
        if not known:
            if db.prereqs(wonder) is None or not db.is_unlocked(wonder, researched, civics):
                continue
            city = max(state.cities, key=lambda c: (c.population, -c.city_id))
            return WonderPick(wonder, city.city_id, None, 0.0)

        options: list[tuple[float, int, int, WonderPick]] = []
        for city in state.cities:
            by_index = {p.index: p for p in city.plots or ()}
            for index in (city.wonder_sites or {}).get(wonder, ()):
                plot = by_index.get(index)
                if plot is None:
                    continue  # tuile hors de la carte exportée (au-delà du 3e anneau)
                bonus = _neighbor_bonus(plot, by_index, db, traits, researched, civics)
                loss = DISTRICT_POTENTIAL_WEIGHT * max(plot.sites.values(), default=0.0)
                score = bonus - loss - resource_penalty(plot, db) + POPULATION_WEIGHT * city.population
                options.append((score, -city.city_id, -index, WonderPick(wonder, city.city_id, plot, bonus)))
        if options:
            return max(options, key=lambda o: o[:3])[3]
    return None


def _neighbor_bonus(
    plot: CityPlot, by_index: dict[int, CityPlot], db: GameDb,
    traits: set[str], researched: set[str], civics: set[str],
) -> float:
    total = 0.0
    for n in plot.neighbors:
        neighbor = by_index.get(n)
        if neighbor is not None and neighbor.district not in (None, WONDER_DISTRICT):
            total += db.district_interaction(neighbor.district, WONDER_DISTRICT, traits, researched, civics)
    return total


def wonder_reason(pick: WonderPick) -> str:
    parts = [WONDER_NOTES.get(pick.wonder, "merveille clé de la stratégie")]
    if pick.plot is not None:
        parts.append("emplacement conseillé sur la page Villes")
    if pick.neighbor_bonus:
        parts.append(f"{pick.neighbor_bonus:+g} d'adjacence aux quartiers voisins")
    return " · ".join(parts)
