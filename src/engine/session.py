"""Attribution d'un game_id quand le mod n'en fournit pas (spec 02 §3.1)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from engine.state import GameState


class GameSession:
    def __init__(self, now: Callable[[], datetime] = datetime.now) -> None:
        self._now = now
        self._game_id: str | None = None
        self._leader: str | None = None
        self._last_turn = -1

    def resolve_game_id(self, state: GameState) -> str:
        if state.game_id:
            self._game_id = state.game_id
        elif self._game_id is None or state.leader != self._leader or state.turn < self._last_turn:
            # Nouvelle partie, ou chargement d'une sauvegarde antérieure : nouvelle branche.
            self._game_id = f"{state.leader}_{self._now():%Y%m%d-%H%M%S}"
        self._leader = state.leader
        self._last_turn = state.turn
        return self._game_id
