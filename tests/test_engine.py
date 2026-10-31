from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest
from websockets.asyncio.client import connect

import contracts
from engine.archive import Archive
from engine.recommendations import build_recommendations, build_status
from engine.session import GameSession
from engine.state import InvalidGameState, parse_game_state
from engine.ws_server import Broadcaster


def encode(data: dict) -> bytes:
    return json.dumps(data).encode("utf-8")


# --- state -------------------------------------------------------------------

def test_parse_valid_state(mvp0_payload: bytes) -> None:
    state = parse_game_state(mvp0_payload)
    assert state.turn == 12
    assert state.trigger == "turn_begin"
    assert state.leader == "LEADER_TRAJAN"
    assert state.yields.gold_per_turn == 8.5
    assert state.current_research == "TECH_HORSEBACK_RIDING"
    assert state.game_id is None


def test_parse_accepts_null_research(mvp0_state: dict) -> None:
    mvp0_state["techs"]["current_research"] = None
    assert parse_game_state(encode(mvp0_state)).current_research is None


@pytest.mark.parametrize("payload", [b"{not json", b"\xff\xfe", b"[]"])
def test_parse_rejects_unreadable(payload: bytes) -> None:
    with pytest.raises(InvalidGameState):
        parse_game_state(payload)


def test_parse_rejects_schema_violation(mvp0_state: dict) -> None:
    del mvp0_state["yields"]["gold"]
    with pytest.raises(InvalidGameState, match="gold"):
        parse_game_state(encode(mvp0_state))


def test_parse_rejects_wrong_schema_version(mvp0_state: dict) -> None:
    mvp0_state["schema_version"] = 2
    with pytest.raises(InvalidGameState):
        parse_game_state(encode(mvp0_state))


# --- session -----------------------------------------------------------------

def test_session_generates_stable_id(mvp0_state: dict) -> None:
    session = GameSession(now=lambda: datetime(2026, 10, 29, 20, 0, 0))
    first = session.resolve_game_id(parse_game_state(encode(mvp0_state)))
    mvp0_state["game"]["turn"] = 13
    assert session.resolve_game_id(parse_game_state(encode(mvp0_state))) == first
    assert first == "LEADER_TRAJAN_20261029-200000"


def test_session_new_id_on_earlier_save(mvp0_state: dict) -> None:
    times = iter([datetime(2026, 1, 1, 10), datetime(2026, 1, 1, 11)])
    session = GameSession(now=lambda: next(times))
    first = session.resolve_game_id(parse_game_state(encode(mvp0_state)))
    mvp0_state["game"]["turn"] = 5
    assert session.resolve_game_id(parse_game_state(encode(mvp0_state))) != first


def test_session_prefers_mod_game_id(mvp0_state: dict) -> None:
    mvp0_state["meta"]["game_id"] = "LEADER_TRAJAN_42"
    assert GameSession().resolve_game_id(parse_game_state(encode(mvp0_state))) == "LEADER_TRAJAN_42"


# --- archive -----------------------------------------------------------------

def test_archive_writes_latest_and_turn_file(tmp_path: Path, mvp0_payload: bytes) -> None:
    state = parse_game_state(mvp0_payload)
    turn_path = Archive(tmp_path).save("LEADER_TRAJAN:2026/10", state)

    assert turn_path == tmp_path / "raw" / "LEADER_TRAJAN_2026_10" / "turn_0012_turn_begin.json"
    assert json.loads(turn_path.read_text(encoding="utf-8")) == state.raw
    assert json.loads((tmp_path / "game_state.json").read_text(encoding="utf-8")) == state.raw


# --- recommendations ---------------------------------------------------------

def test_recommendations_message_matches_contract(mvp0_payload: bytes) -> None:
    message = build_recommendations(parse_game_state(mvp0_payload), "g1")
    assert contracts.first_error("recommendations", message) is None
    assert message["snapshot"]["gold"] == 45.2
    assert message["actions"] == []


def test_turn_end_keeps_previous_lists(mvp0_state: dict) -> None:
    previous = build_recommendations(parse_game_state(encode(mvp0_state)), "g1")
    previous["actions"] = [{
        "id": "x", "category": "other", "title": "t", "reason": "r", "priority": 1, "source": "rules",
    }]
    mvp0_state["meta"]["trigger"] = "turn_end"
    mvp0_state["yields"]["gold"] = 60
    message = build_recommendations(parse_game_state(encode(mvp0_state)), "g1", previous)
    assert message["actions"] == previous["actions"]
    assert message["snapshot"]["gold"] == 60


@pytest.mark.parametrize("state", ["waiting_for_game", "ok", "degraded"])
def test_status_message_matches_contract(state: str) -> None:
    assert contracts.first_error("recommendations", build_status(state, turn=3, game_id="g")) is None


# --- ws_server ---------------------------------------------------------------

def test_broadcaster_replays_last_messages_and_broadcasts(mvp0_payload: bytes) -> None:
    async def scenario() -> list[dict]:
        broadcaster = Broadcaster("127.0.0.1", 0)
        await broadcaster.start()
        try:
            broadcaster.publish(build_status("waiting_for_game"))
            broadcaster.publish({"type": "status", "schema_version": 1, "state": "bogus"})  # rejeté
            async with connect(f"ws://127.0.0.1:{broadcaster.port}") as ws:
                received = [json.loads(await asyncio.wait_for(ws.recv(), 2))]
                broadcaster.publish(build_recommendations(parse_game_state(mvp0_payload), "g1"))
                received.append(json.loads(await asyncio.wait_for(ws.recv(), 2)))
                return received
        finally:
            await broadcaster.stop()

    status, recommendations = asyncio.run(scenario())
    assert status["state"] == "waiting_for_game"
    assert recommendations["type"] == "recommendations"
    assert recommendations["turn"] == 12
