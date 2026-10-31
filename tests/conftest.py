from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
CHUNK_SIZE = 900


def to_log_lines(payload: bytes, msg_id: int, chunk_size: int = CHUNK_SIZE, prefix: bytes = b"GameStateExporter: ") -> list[bytes]:
    """Reproduit le découpage du mod (spec 01 §4.2), fragmentation à l'octet."""
    chunks = [payload[i:i + chunk_size] for i in range(0, len(payload), chunk_size)] or [b""]
    total = len(chunks)
    return [
        prefix + b"[CIVOVL] %d %d/%d " % (msg_id, part, total) + chunk
        for part, chunk in enumerate(chunks, start=1)
    ]


@pytest.fixture(scope="session")
def game_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Base de règles réelle (extrait) : voir scripts/extract_game_db_fixture.py."""
    path = tmp_path_factory.mktemp("db") / "game_db.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript((FIXTURES / "game_db.sql").read_text(encoding="utf-8"))
    conn.close()
    return path


@pytest.fixture(scope="session")
def game_db(game_db_path: Path):
    from engine.game_db import GameDb

    return GameDb.load(game_db_path, game_db_path, "fr_FR")


@pytest.fixture
def mvp1_state_dict() -> dict:
    return json.loads((FIXTURES / "game_state_mvp1.json").read_text(encoding="utf-8"))


def state_from(data: dict):
    from engine.state import parse_game_state

    return parse_game_state(json.dumps(data).encode("utf-8"))


@pytest.fixture
def mvp0_state() -> dict:
    return json.loads((FIXTURES / "game_state_mvp0.json").read_text(encoding="utf-8"))


@pytest.fixture
def mvp0_payload(mvp0_state: dict) -> bytes:
    return json.dumps(mvp0_state, separators=(",", ":")).encode("utf-8")
