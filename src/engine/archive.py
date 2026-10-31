"""Écriture du dernier état et archivage par tour (spec 02 §2)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from engine.state import GameState

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9_.-]")


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class Archive:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def game_dir(self, game_id: str) -> Path:
        return self.data_dir / "raw" / _UNSAFE_CHARS.sub("_", game_id)

    def save(self, game_id: str, state: GameState) -> Path:
        """Écrit data/game_state.json et data/raw/<game_id>/turn_XXXX_<trigger>.json."""
        write_json_atomic(self.data_dir / "game_state.json", state.raw)
        turn_path = self.game_dir(game_id) / f"turn_{state.turn:04d}_{state.trigger}.json"
        write_json_atomic(turn_path, state.raw)
        return turn_path
