"""Règle eureka_reachable : un boost proche s'obtient en produisant une unité, un bâtiment,
un quartier ou un aménagement que le joueur peut déjà réaliser.

Types de boost couverts (les autres sont ignorés, spec 02 §5.2) :
TRAIN_UNIT, OWN_X_UNITS_OF_TYPE, CONSTRUCT_BUILDING, HAVE_X_BUILDINGS, HAVE_X_DISTRICTS, HAVE_X_IMPROVEMENTS.
"""

from __future__ import annotations

from engine.game_db import Boost, GameDb
from engine.rules import Action
from engine.state import GameState
from engine.text import de

MAX_MISSING = 2  # au-delà, le boost n'est plus « à portée »


class EurekaReachable:
    id = "eureka_reachable"

    def evaluate(self, state: GameState, db: GameDb) -> list[Action]:
        researched = set(state.researched)
        civics = set(state.civics_unlocked or ())
        traits = db.player_traits(state.civilization, state.leader)

        candidates: list[str] = [
            t for t in db.available_techs(researched) if t not in state.boosted_techs
        ]
        if state.civics_unlocked is not None:
            candidates += [c for c in db.available_civics(civics) if c not in state.boosted_civics]

        actions = []
        for target in candidates:
            boost = db.boosts.get(target)
            if boost is None:
                continue
            step = _missing_step(boost, state, db, researched, civics, traits)
            if step is None:
                continue
            category, verb, item, missing = step
            kind = "Eurêka" if target.startswith("TECH_") else "Inspiration"
            is_current = target in (state.current_research, state.current_civic)
            actions.append(Action(
                id=f"{self.id}:{target}",
                category=category,
                title=f"{verb} {missing} × {db.name(item)}" if missing > 1 else f"{verb} {db.name(item)}",
                reason=f"Déclenche l'{kind} {de(db.name(target))} (−{boost.percent} %)",
                priority=70 if is_current else 60,
                target_type=item,
            ))
        return actions


def _missing_step(
    boost: Boost, state: GameState, db: GameDb, researched: set[str], civics: set[str], traits: set[str]
) -> tuple[str, str, str, int] | None:
    """(catégorie, verbe, type à produire, quantité manquante) ou None si hors de portée."""
    cls = boost.boost_class

    if cls in ("BOOST_TRIGGER_TRAIN_UNIT", "BOOST_TRIGGER_OWN_X_UNITS_OF_TYPE") and boost.unit:
        # Unités navales : il faut une ville au bord de l'eau (inconnu -> on ne bloque pas).
        if boost.unit in db.naval_units and all(c.coastal is False for c in state.cities):
            return None
        variants = db.variants(boost.unit)
        have = 0 if cls == "BOOST_TRIGGER_TRAIN_UNIT" else sum(u.type in variants for u in state.units)
        return _producible("production", "Produire", boost.unit, boost.count - have, db, researched, civics, traits)

    if cls in ("BOOST_TRIGGER_CONSTRUCT_BUILDING", "BOOST_TRIGGER_HAVE_X_BUILDINGS") and boost.building:
        variants = db.variants(boost.building)
        have = sum(bool(variants & c.buildings) for c in state.cities)
        step = _producible("production", "Construire", boost.building, boost.count - have, db, researched, civics, traits)
        district = db.building_district.get(boost.building)
        if step is not None and district and district != "DISTRICT_CITY_CENTER":
            if not any(db.variants(district) & c.districts for c in state.cities):
                return None  # il faudrait d'abord le quartier
        return step

    if cls == "BOOST_TRIGGER_HAVE_X_DISTRICTS" and boost.district:
        variants = db.variants(boost.district)
        have = sum(bool(variants & c.districts) for c in state.cities)
        return _producible("production", "Construire", boost.district, boost.count - have, db, researched, civics, traits)

    if cls == "BOOST_TRIGGER_HAVE_X_IMPROVEMENTS" and boost.improvement:
        have = sum(t.owner == "self" and t.improvement == boost.improvement for t in state.tiles)
        return _producible("unit", "Aménager", boost.improvement, boost.count - have, db, researched, civics, traits)

    return None


def _producible(
    category: str, verb: str, generic: str, missing: int,
    db: GameDb, researched: set[str], civics: set[str], traits: set[str],
) -> tuple[str, str, str, int] | None:
    if not 0 < missing <= MAX_MISSING:
        return None
    item = db.resolve_for_player(generic, traits)
    if item is None or not db.is_unlocked(item, researched, civics):
        return None
    return category, verb, item, missing
