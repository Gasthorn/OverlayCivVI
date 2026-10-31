"""Règle housing_cap : population ≥ logement − 1."""

from __future__ import annotations

from engine.game_db import GameDb
from engine.rules import Action
from engine.state import City, GameState

GRANARY = "BUILDING_GRANARY"


class HousingCap:
    id = "housing_cap"

    def evaluate(self, state: GameState, db: GameDb) -> list[Action]:
        traits = db.player_traits(state.civilization, state.leader)
        civics = set(state.civics_unlocked or ())
        actions = []
        for city in state.cities:
            if city.housing is None or city.population < city.housing - 1:
                continue
            saturated = city.population >= city.housing
            granary = self._granary_for(city, state, db, traits, civics)
            if granary is not None:
                title, target = f"Construire {db.name(granary)} à {city.name}", granary
            else:
                title, target = f"Augmenter le logement à {city.name}", None
            actions.append(Action(
                id=f"{self.id}:{city.city_id}",
                category="production",
                title=title,
                reason=(
                    f"Population {city.population} / logement {city.housing:g} : "
                    + ("la croissance est très ralentie" if saturated else "la croissance ralentit")
                ),
                priority=65 if saturated else 50,
                target_type=target,
                city_id=city.city_id,
            ))
        return actions

    @staticmethod
    def _granary_for(city: City, state: GameState, db: GameDb, traits: set[str], civics: set[str]) -> str | None:
        granary = db.resolve_for_player(GRANARY, traits)
        if granary is None or db.variants(GRANARY) & city.buildings:
            return None
        if not db.is_unlocked(granary, set(state.researched), civics):
            return None
        return granary
