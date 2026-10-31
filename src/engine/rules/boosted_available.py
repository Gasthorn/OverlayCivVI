"""Règle boosted_available : une technologie ou un dogme disponible a déjà son boost."""

from __future__ import annotations

from engine.game_db import GameDb
from engine.rules import Action
from engine.state import GameState


class BoostedAvailable:
    id = "boosted_available"

    def evaluate(self, state: GameState, db: GameDb) -> list[Action]:
        actions = []
        current_boosted = state.current_research in state.boosted_techs
        for tech in sorted(state.boosted_techs):
            if tech == state.current_research or not db.tech_is_available(tech, set(state.researched)):
                continue
            actions.append(Action(
                id=f"{self.id}:{tech}", category="research", title=f"Rechercher {db.name(tech)}",
                reason=f"Eurêka déjà obtenu : −{_percent(db, tech)} % du coût",
                priority=40 if current_boosted else 70, target_type=tech,
            ))

        if state.civics_unlocked is not None:
            current_boosted = state.current_civic in state.boosted_civics
            for civic in sorted(state.boosted_civics):
                if civic == state.current_civic or not db.civic_is_available(civic, set(state.civics_unlocked)):
                    continue
                actions.append(Action(
                    id=f"{self.id}:{civic}", category="civic", title=f"Adopter {db.name(civic)}",
                    reason=f"Inspiration déjà obtenue : −{_percent(db, civic)} % du coût",
                    priority=40 if current_boosted else 70, target_type=civic,
                ))
        return actions


def _percent(db: GameDb, target: str) -> int:
    boost = db.boosts.get(target)
    return boost.percent if boost else 50
