"""Stratégie suivie par le joueur, mémorisée par partie dans data/followed_strategies.json (spec 02 §6.5)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from engine.archive import write_json_atomic

log = logging.getLogger(__name__)


class FollowedStrategies:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "followed_strategies.json"
        self._choices: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Stratégies suivies illisibles (%s), réinitialisées", exc)
            return {}
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}

    def get(self, game_id: str | None) -> str | None:
        return self._choices.get(game_id) if game_id else None

    def set(self, game_id: str, strategy_id: str | None) -> None:
        if strategy_id is None:
            self._choices.pop(game_id, None)
        else:
            self._choices[game_id] = strategy_id
        try:
            write_json_atomic(self.path, self._choices)
        except OSError as exc:
            log.error("Impossible d'enregistrer la stratégie suivie : %s", exc)
