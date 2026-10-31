"""Règle settle_site : un colon attend, voici le meilleur site découvert (spec 02 §9)."""

from __future__ import annotations

from engine.game_db import GameDb
from engine.rules import Action
from engine.settling import settle_sites
from engine.state import GameState

SETTLER = "UNIT_SETTLER"


class SettleSite:
    id = "settle_site"

    def evaluate(self, state: GameState, db: GameDb) -> list[Action]:
        if not any(u.type in db.variants(SETTLER) for u in state.units):
            return []
        sites = settle_sites(state, db, limit=1)
        if not sites:
            return []
        (site,) = sites
        where = f" · à {site.distance} tuiles de {site.nearest_city}" if site.nearest_city else ""
        return [Action(
            id=f"{self.id}:{site.hex_x}:{site.hex_y}",
            category="unit",
            title="Fonder une ville sur le site n°1 (page Colonisation)",
            reason=" · ".join(site.reasons(3)) + where,
            priority=76,
            target_type=SETTLER,
        )]
