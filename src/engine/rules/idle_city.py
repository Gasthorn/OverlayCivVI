"""Règle idle_city : ville sans production en cours."""

from __future__ import annotations

from engine.game_db import GameDb
from engine.rules import Action
from engine.state import GameState


class IdleCity:
    id = "idle_city"

    def evaluate(self, state: GameState, db: GameDb) -> list[Action]:
        return [
            Action(
                id=f"{self.id}:{city.city_id}", category="production",
                title=f"Choisir une production à {city.name}",
                reason="La ville ne produit rien", priority=85, city_id=city.city_id,
            )
            for city in state.cities
            if city.current_production is None
        ]
