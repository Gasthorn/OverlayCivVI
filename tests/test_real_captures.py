"""Tests sur des données capturées en jeu (partie solo, Macédoine, 2026-10-29)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import FIXTURES
from engine.log_tailer import LuaLogTailer
from engine.milestones import MilestoneTracker
from engine.recommendations import build_recommendations
from engine.rules import run_rules
from engine.state import parse_game_state

import contracts


def test_real_lua_log_excerpt_is_fully_decoded() -> None:
    log_path = FIXTURES / "lua_log_real_excerpt.log"
    expected = log_path.read_bytes().count(b"[CIVOVL] ")
    states = [parse_game_state(m) for m in LuaLogTailer(log_path).poll()]

    assert len(states) == expected > 0
    assert states[0].trigger == "game_loaded"
    assert [s.turn for s in states] == sorted(s.turn for s in states)
    assert {s.leader for s in states} == {"LEADER_JFD_OLYMPIAS"}


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("game_state_*.json")), ids=lambda p: p.name)
def test_game_state_fixtures_produce_valid_messages(path: Path, game_db) -> None:
    state = parse_game_state(path.read_bytes())
    actions = [a.to_message() for a in run_rules(state, game_db)]
    milestones = MilestoneTracker().update("g", state, game_db)
    message = build_recommendations(state, "g", milestones=milestones, actions=actions)
    assert contracts.first_error("recommendations", message) is None
    assert json.loads(path.read_text(encoding="utf-8")) == state.raw


def test_real_turn_50_recommendations(game_db) -> None:
    """Partie Kongo réelle au tour 50 (vitesse En ligne), capturée le 2026-10-29."""
    state = parse_game_state((FIXTURES / "game_state_real_t050.json").read_bytes())
    assert (len(state.cities), state.game_speed) == (6, "GAMESPEED_ONLINE")
    titles = [a.title for a in run_rules(state, game_db)]
    assert "Adopter Tradition militaire" in titles
    assert "Rechercher Travail du fer" in titles
