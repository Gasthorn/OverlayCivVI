"""Règle idle_research : aucune technologie ou aucun dogme en cours."""

from __future__ import annotations

from engine.game_db import GameDb
from engine.rules import Action
from engine.state import GameState


class IdleResearch:
    id = "idle_research"

    def evaluate(self, state: GameState, db: GameDb) -> list[Action]:
        actions = []
        if state.current_research is None and db.available_techs(state.researched):
            actions.append(Action(
                id=f"{self.id}:tech", category="research", title="Choisir une recherche",
                reason="Aucune technologie en cours", priority=90,
            ))
        if (
            state.civics_unlocked is not None
            and state.current_civic is None
            and db.available_civics(state.civics_unlocked)
        ):
            actions.append(Action(
                id=f"{self.id}:civic", category="civic", title="Choisir un dogme",
                reason="Aucun dogme en cours", priority=90,
            ))
        return actions
