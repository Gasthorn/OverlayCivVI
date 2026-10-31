from __future__ import annotations

import copy
from pathlib import Path

from conftest import state_from
from engine.archive import Archive
from engine.game_db import GameDb
from engine.milestones import MilestoneTracker


def test_upcoming_research_and_civic_eta(game_db: GameDb, mvp1_state_dict: dict) -> None:
    mvp1_state_dict["civics"].update(current_civic="CIVIC_FOREIGN_TRADE", civic_progress=10, civic_cost=40)
    milestones = MilestoneTracker().update("g", state_from(mvp1_state_dict), game_db)
    upcoming = [m for m in milestones if m["status"] == "upcoming"]
    # Bronze : (80 - 20) / 4.5 = 13,3 -> 14 tours ; dogme : (40 - 10) / 3.2 = 9,4 -> 10 tours.
    assert upcoming == [
        {"turn": 25, "label": "≈ Dogme : Commerce avec l'étranger", "status": "upcoming"},
        {"turn": 29, "label": "≈ Recherche : Travail du bronze", "status": "upcoming"},
    ]


def test_city_and_government_events(game_db: GameDb, mvp1_state_dict: dict) -> None:
    tracker = MilestoneTracker()
    first = copy.deepcopy(mvp1_state_dict)
    first["game"]["turn"], first["cities"] = 2, first["cities"][:1]
    tracker.update("g", state_from(first), game_db)

    later = copy.deepcopy(mvp1_state_dict)
    later["game"]["turn"] = 22
    later["player"]["government"] = "GOVERNMENT_AUTOCRACY"
    done = [m for m in tracker.update("g", state_from(later), game_db) if m["status"] == "done"]
    assert done == [
        {"turn": 2, "label": "Capitale fondée : Pella", "status": "done"},
        {"turn": 22, "label": "Ville fondée : Aigai", "status": "done"},
        {"turn": 22, "label": "Gouvernement : Autocratie", "status": "done"},
    ]


def test_resumed_game_does_not_invent_foundations(game_db: GameDb, mvp1_state_dict: dict) -> None:
    """Premier état observé au tour 15 : les villes existantes ne sont pas « fondées au tour 15 »."""
    tracker = MilestoneTracker()
    first = copy.deepcopy(mvp1_state_dict)
    first["cities"] = first["cities"][:1]
    assert not [m for m in tracker.update("g", state_from(first), game_db) if m["status"] == "done"]

    later = copy.deepcopy(mvp1_state_dict)
    later["game"]["turn"] = 18
    done = [m for m in tracker.update("g", state_from(later), game_db) if m["status"] == "done"]
    assert done == [{"turn": 18, "label": "Ville fondée : Aigai", "status": "done"}]


def test_history_rebuilt_from_archive(tmp_path: Path, game_db: GameDb, mvp1_state_dict: dict) -> None:
    archive = Archive(tmp_path)
    early = copy.deepcopy(mvp1_state_dict)
    early["game"]["turn"], early["cities"] = 3, early["cities"][:1]
    archive.save("g", state_from(early))
    current = state_from(mvp1_state_dict)
    archive.save("g", current)

    done = [m for m in MilestoneTracker(archive).update("g", current, game_db) if m["status"] == "done"]
    assert done == [
        {"turn": 3, "label": "Capitale fondée : Pella", "status": "done"},
        {"turn": 15, "label": "Ville fondée : Aigai", "status": "done"},
    ]


def test_no_eta_without_science(game_db: GameDb, mvp1_state_dict: dict) -> None:
    mvp1_state_dict["yields"]["science_per_turn"] = 0
    milestones = MilestoneTracker().update("g", state_from(mvp1_state_dict), game_db)
    assert not [m for m in milestones if m["status"] == "upcoming"]
