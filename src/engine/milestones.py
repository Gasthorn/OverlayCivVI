"""Jalons de la partie (spec 02 §5.3) : événements passés et échéances estimées.

Les événements passés sont détectés par comparaison entre états successifs. Au premier état
d'une partie, l'historique est reconstruit à partir des archives (data/raw/<game_id>/).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from engine.archive import Archive
from engine.game_db import GameDb
from engine.state import GameState, InvalidGameState, parse_game_state

log = logging.getLogger(__name__)

MAX_DONE = 6
FIRST_TURNS = 5  # au-delà, un premier état observé est une partie reprise en cours de route
_TRIGGER_ORDER = {"game_loaded": 0, "turn_begin": 1, "state_changed": 2, "turn_end": 3}


@dataclass
class _History:
    events: list[tuple[int, str]] = field(default_factory=list)
    city_ids: set[int] = field(default_factory=set)
    government: str | None = None
    era: str | None = None
    seen: set[tuple[int, str]] = field(default_factory=set)
    started: bool = False


class MilestoneTracker:
    def __init__(self, archive: Archive | None = None) -> None:
        self._archive = archive
        self._games: dict[str, _History] = {}

    def update(self, game_id: str, state: GameState, db: GameDb | None) -> list[dict[str, Any]]:
        history = self._games.get(game_id)
        if history is None:
            history = self._games[game_id] = _History()
            for archived in self._load_archive(game_id):
                self._feed(history, archived, db)
        self._feed(history, state, db)

        done = [
            {"turn": turn, "label": label, "status": "done"}
            for turn, label in sorted(history.events, key=lambda e: e[0])[-MAX_DONE:]
        ]
        return done + _upcoming(state, db)

    def _feed(self, history: _History, state: GameState, db: GameDb | None) -> None:
        key = (state.turn, state.trigger)
        if key in history.seen:
            return
        history.seen.add(key)
        name = db.name if db is not None else (lambda t: t or "—")
        # Partie reprise en cours de route : les villes déjà là n'ont pas été fondées « maintenant ».
        silent = not history.started and state.turn > FIRST_TURNS

        for city in state.cities:
            if city.city_id not in history.city_ids:
                history.city_ids.add(city.city_id)
                if silent:
                    continue
                label = f"Capitale fondée : {city.name}" if city.is_capital else f"Ville fondée : {city.name}"
                history.events.append((state.turn, label))

        if state.government and state.government != history.government:
            if history.started:
                history.events.append((state.turn, f"Gouvernement : {name(state.government)}"))
            history.government = state.government

        if state.era and state.era != history.era:
            if history.started:
                history.events.append((state.turn, f"Nouvelle ère : {name(state.era)}"))
            history.era = state.era
        history.started = True

    def _load_archive(self, game_id: str) -> list[GameState]:
        if self._archive is None:
            return []
        directory = self._archive.game_dir(game_id)
        states = []
        for path in directory.glob("turn_*.json"):
            try:
                states.append(parse_game_state(path.read_bytes()))
            except (OSError, InvalidGameState) as exc:
                log.warning("Archive ignorée (%s) : %s", path.name, exc)
        return sorted(states, key=lambda s: (s.turn, _TRIGGER_ORDER.get(s.trigger, 9)))


def _upcoming(state: GameState, db: GameDb | None) -> list[dict[str, Any]]:
    name = db.name if db is not None else (lambda t: t or "—")
    items = []
    for target, progress, cost, rate, kind in (
        (state.current_research, state.research_progress, state.research_cost, state.yields.science_per_turn, "Recherche"),
        (state.current_civic, state.civic_progress, state.civic_cost, state.yields.culture_per_turn, "Dogme"),
    ):
        if not target or cost is None or not rate or rate <= 0:
            continue
        turns = max(1, math.ceil((cost - (progress or 0)) / rate))
        items.append({"turn": state.turn + turns, "label": f"≈ {kind} : {name(target)}", "status": "upcoming"})
    return sorted(items, key=lambda m: m["turn"])
