"""Règle unlock_visible_resource : des ressources visibles près des villes attendent
une technologie disponible pour être aménagées."""

from __future__ import annotations

from collections import Counter, defaultdict

from engine.game_db import GameDb
from engine.rules import Action
from engine.state import GameState


class UnlockVisibleResource:
    id = "unlock_visible_resource"

    def evaluate(self, state: GameState, db: GameDb) -> list[Action]:
        researched = set(state.researched)
        civics = set(state.civics_unlocked or ())
        traits = db.player_traits(state.civilization, state.leader)

        resources_by_tech: dict[str, Counter[str]] = defaultdict(Counter)
        for tile in state.tiles:
            if tile.resource is None or tile.owner == "other" or tile.improvement is not None:
                continue
            tech = self._unlocking_tech(tile.resource, db, researched, civics, traits)
            if tech is not None:
                resources_by_tech[tech][tile.resource] += 1

        actions = []
        for tech, resources in sorted(resources_by_tech.items()):
            total = sum(resources.values())
            listing = ", ".join(
                f"{db.name(r)} ×{n}" if n > 1 else db.name(r) for r, n in resources.most_common()
            )
            actions.append(Action(
                id=f"{self.id}:{tech}", category="research", title=f"Rechercher {db.name(tech)}",
                reason=f"Permet d'aménager {total} ressource{'s' if total > 1 else ''} près de vos villes : {listing}",
                priority=50 + 3 * min(total, 5), target_type=tech,
            ))
        return actions

    @staticmethod
    def _unlocking_tech(
        resource: str, db: GameDb, researched: set[str], civics: set[str], traits: set[str]
    ) -> str | None:
        """Technologie disponible qui débloque un aménagement de la ressource ; None si déjà aménageable."""
        candidates = []
        for improvement in db.improvements_for_resource.get(resource, ()):
            info = db.prereqs(improvement)
            if info is None or (info.trait is not None and info.trait not in traits):
                continue
            if db.is_unlocked(improvement, researched, civics):
                return None
            if info.tech and info.civic is None and db.tech_is_available(info.tech, researched):
                candidates.append(info.tech)
        return min(candidates, key=lambda t: (db.tech_costs.get(t, 0), t)) if candidates else None
