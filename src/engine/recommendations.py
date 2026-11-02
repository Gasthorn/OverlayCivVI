"""Construction des messages publiés vers l'overlay (spec 04)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from engine.state import GameState

SCHEMA_VERSION = 2  # 2 : retrait de `milestones`

# Recalcul complet des listes ; les autres déclencheurs ne rafraîchissent que le snapshot.
RECOMPUTE_TRIGGERS = frozenset({"game_loaded", "turn_begin", "state_changed"})


def build_status(
    state: str, turn: int | None = None, game_id: str | None = None, detail: str | None = None
) -> dict[str, Any]:
    return {
        "type": "status",
        "schema_version": SCHEMA_VERSION,
        "state": state,
        "turn": turn,
        "game_id": game_id,
        "detail": detail,
    }


def build_recommendations(
    state: GameState,
    game_id: str,
    previous: dict[str, Any] | None = None,
    *,
    actions: list[dict[str, Any]] | None = None,
    strategies: list[dict[str, Any]] | None = None,
    cities: list[dict[str, Any]] | None = None,
    settle: dict[str, Any] | None = None,
    followed_strategy: str | None = None,
    recompute: bool = False,
) -> dict[str, Any]:
    """Sur `turn_end`, seul le snapshot est rafraîchi : les listes du message précédent sont conservées
    (sauf `recompute`, demandé quand le joueur change de stratégie suivie)."""
    keep_previous = not recompute and state.trigger not in RECOMPUTE_TRIGGERS and previous is not None
    y = state.yields
    return {
        "type": "recommendations",
        "schema_version": SCHEMA_VERSION,
        "game_id": game_id,
        "turn": state.turn,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "followed_strategy": followed_strategy,
        "snapshot": {
            "era": state.era,
            "gold": y.gold,
            "gold_per_turn": y.gold_per_turn,
            "science_per_turn": y.science_per_turn,
            "culture_per_turn": y.culture_per_turn,
            "faith": y.faith,
        },
        "strategies": previous["strategies"] if keep_previous else (strategies or []),
        "actions": previous["actions"] if keep_previous else (actions or []),
        "cities": previous.get("cities", []) if keep_previous else (cities or []),
        "settle": previous.get("settle") if keep_previous else settle,
    }
