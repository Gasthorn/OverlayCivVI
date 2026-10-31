"""Moteur de règles (spec 02 §5) : chaque règle est pure, déterministe et testable sur fixture."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any, Protocol

from engine.game_db import GameDb
from engine.state import GameState

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Action:
    id: str
    category: str          # research | civic | production | unit | policy | other
    title: str
    reason: str
    priority: int          # 0..100
    source: str = "rules"
    target_type: str | None = None
    city_id: int | None = None
    unit_id: int | None = None
    strategy: str | None = None  # stratégie servie par l'action (actions de focus)

    def to_message(self) -> dict[str, Any]:
        message = {
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "reason": self.reason,
            "priority": max(0, min(100, self.priority)),
            "source": self.source,
            "target": {"type": self.target_type, "city_id": self.city_id, "unit_id": self.unit_id},
        }
        if self.strategy:
            message["strategy"] = self.strategy
        return message


class Rule(Protocol):
    id: str

    def evaluate(self, state: GameState, db: GameDb) -> list[Action]: ...


def all_rules() -> list[Rule]:
    from engine.rules.boosted_available import BoostedAvailable
    from engine.rules.eureka_reachable import EurekaReachable
    from engine.rules.housing_cap import HousingCap
    from engine.rules.idle_city import IdleCity
    from engine.rules.idle_research import IdleResearch
    from engine.rules.settle_site import SettleSite
    from engine.rules.unlock_visible_resource import UnlockVisibleResource

    return [
        IdleResearch(), BoostedAvailable(), EurekaReachable(), IdleCity(), HousingCap(), UnlockVisibleResource(),
        SettleSite(),
    ]


URGENT_PRIORITY = 80   # au-dessus : actions bloquantes (rien en cours), jamais rétrogradées
UNFOCUSED_PENALTY = 15  # rétrogradation des autres actions quand une stratégie est suivie


def run_rules(
    state: GameState,
    db: GameDb,
    rules: list[Rule] | None = None,
    followed_strategy: str | None = None,
) -> list[Action]:
    """Évalue les règles (et le focus de la stratégie suivie), fusionne les doublons et trie."""
    actions: list[Action] = []
    for rule in rules if rules is not None else all_rules():
        try:
            actions.extend(rule.evaluate(state, db))
        except Exception:  # une règle défaillante ne doit pas priver l'UI des autres
            log.exception("Règle %s en échec, ignorée pour ce tour", rule.id)

    if followed_strategy:
        from engine.strategy_focus import focus_actions

        try:
            focus = focus_actions(state, db, followed_strategy)
        except Exception:
            log.exception("Focus %s en échec, ignoré pour ce tour", followed_strategy)
            focus = []
        actions = [
            a if a.priority >= URGENT_PRIORITY else replace(a, priority=a.priority - UNFOCUSED_PENALTY)
            for a in actions
        ] + focus

    return sorted(_merge(actions), key=lambda a: (-a.priority, a.id))


def _merge(actions: list[Action]) -> list[Action]:
    """Deux règles qui recommandent la même chose (même cible) donnent une seule action."""
    merged: dict[tuple[str, str | None, int | None, int | None], Action] = {}
    for action in actions:
        key = (action.category, action.target_type, action.city_id, action.unit_id)
        if action.target_type is None and action.city_id is None:
            key = (action.id, None, None, None)
        existing = merged.get(key)
        if existing is None:
            merged[key] = action
            continue
        first, second = (existing, action) if existing.priority >= action.priority else (action, existing)
        merged[key] = replace(
            first,
            reason=f"{first.reason} · {second.reason}",
            priority=min(100, first.priority + 5),
            strategy=first.strategy or second.strategy,
        )
    return list(merged.values())
