"""Merveilles de la stratégie suivie (spec 02 §6.7) : choix, emplacement, action et carte."""

from __future__ import annotations

import copy

import contracts
from city_map import hex_patch, ring1
from conftest import state_from
from engine.city_layout import CityPlotsCache, city_layouts
from engine.game_db import WONDER_DISTRICT, GameDb
from engine.strategy_focus import focus_actions
from engine.wonders import wonder_pick

CENTER = (10, 10)
NEXT_TO_THEATER = (11, 10)   # voisine de la Place du théâtre en (12, 10)
FAR_FROM_THEATER = (9, 10)


def with_wonder_sites(state_dict: dict, wonders: dict[str, list[tuple[int, int]]], tiles=None) -> dict:
    data = copy.deepcopy(state_dict)
    tiles = {(12, 10): {"district": "DISTRICT_THEATER"}} | (tiles or {})
    plots = hex_patch(CENTER, ring1(CENTER), tiles)
    index = {(p["hex_x"], p["hex_y"]): p["index"] for p in plots}
    data["cities"][0]["plots"] = plots
    data["cities"][0]["wonder_sites"] = {w: [index[c] for c in coords] for w, coords in wonders.items()}
    return data


def test_wonder_counts_only_for_wonder_adjacency(game_db: GameDb) -> None:
    # BBG : Place du théâtre +2 par merveille voisine ; une merveille n'est pas un « quartier voisin ».
    assert game_db.district_interaction("DISTRICT_THEATER", WONDER_DISTRICT, set(), set(), set()) == 2
    assert game_db.district_interaction("DISTRICT_CAMPUS", WONDER_DISTRICT, set(), set(), set()) == 0


def test_wonder_goes_next_to_the_theater(game_db: GameDb, mvp1_state_dict: dict) -> None:
    data = with_wonder_sites(mvp1_state_dict, {"BUILDING_STONEHENGE": [FAR_FROM_THEATER, NEXT_TO_THEATER]})
    pick = wonder_pick(state_from(data), game_db, "religious_victory")
    assert (pick.wonder, pick.city_id) == ("BUILDING_STONEHENGE", 65536)
    assert ((pick.plot.hex_x, pick.plot.hex_y), pick.neighbor_bonus) == (NEXT_TO_THEATER, 2)


def test_wonder_avoids_good_district_tiles(game_db: GameDb, mvp1_state_dict: dict) -> None:
    tiles = {NEXT_TO_THEATER: {"sites": {"DISTRICT_HOLY_SITE": 6}}}
    data = with_wonder_sites(mvp1_state_dict, {"BUILDING_STONEHENGE": [FAR_FROM_THEATER, NEXT_TO_THEATER]}, tiles)
    pick = wonder_pick(state_from(data), game_db, "religious_victory")
    assert (pick.plot.hex_x, pick.plot.hex_y) == FAR_FROM_THEATER  # +2 au théâtre < 3 d'adjacence perdus


def test_next_wonder_when_first_is_built_or_gone(game_db: GameDb, mvp1_state_dict: dict) -> None:
    # Stonehenge absent des merveilles lançables (construite ailleurs) : la suivante du plan.
    data = with_wonder_sites(mvp1_state_dict, {"BUILDING_MAHABODHI_TEMPLE": [FAR_FROM_THEATER]})
    assert wonder_pick(state_from(data), game_db, "religious_victory").wonder == "BUILDING_MAHABODHI_TEMPLE"
    data["cities"][1]["buildings"].append("BUILDING_MAHABODHI_TEMPLE")
    assert wonder_pick(state_from(data), game_db, "religious_victory") is None


def test_one_plan_wonder_at_a_time(game_db: GameDb, mvp1_state_dict: dict) -> None:
    data = with_wonder_sites(mvp1_state_dict, {"BUILDING_MAHABODHI_TEMPLE": [FAR_FROM_THEATER]})
    data["cities"][1]["current_production"] = "BUILDING_STONEHENGE"
    assert wonder_pick(state_from(data), game_db, "religious_victory") is None


def test_wonder_action(game_db: GameDb, mvp1_state_dict: dict) -> None:
    data = with_wonder_sites(mvp1_state_dict, {"BUILDING_STONEHENGE": [NEXT_TO_THEATER]})
    (action,) = [a for a in focus_actions(state_from(data), game_db, "religious_victory") if a.id.endswith(":wonder")]
    assert (action.title, action.priority, action.target_type) == ("Construire Stonehenge à Pella", 74, "BUILDING_STONEHENGE")
    assert "Grand Prophète gratuit" in action.reason and "page Villes" in action.reason and "+2" in action.reason


def test_wonder_without_known_sites_uses_unlock_state(game_db: GameDb, mvp1_state_dict: dict) -> None:
    state = state_from(mvp1_state_dict)
    assert wonder_pick(state, game_db, "religious_victory") is None  # Astrologie manquante
    mvp1_state_dict["techs"]["researched"] += ["TECH_ASTROLOGY"]
    pick = wonder_pick(state_from(mvp1_state_dict), game_db, "religious_victory")
    assert (pick.wonder, pick.city_id, pick.plot) == ("BUILDING_STONEHENGE", 65536, None)


def test_wonder_tile_is_reserved_on_the_city_map(game_db: GameDb, mvp1_state_dict: dict) -> None:
    # La meilleure case de Lieu saint est celle de la merveille : le Lieu saint se place ailleurs.
    tiles = {
        FAR_FROM_THEATER: {"sites": {"DISTRICT_HOLY_SITE": 1}},
        (10, 9): {"sites": {"DISTRICT_HOLY_SITE": 0}},
    }
    data = with_wonder_sites(mvp1_state_dict, {"BUILDING_STONEHENGE": [FAR_FROM_THEATER]}, tiles)
    data["techs"]["researched"] += ["TECH_ASTROLOGY"]
    state = state_from(data)
    (city,) = city_layouts(state, game_db, CityPlotsCache().update("g", state), "religious_victory")
    wonder, holy_site = city["layout"]
    assert (wonder["district"], wonder["kind"], wonder["wonder"]) == ("BUILDING_STONEHENGE", WONDER_DISTRICT, True)
    assert (wonder["hex_x"], wonder["hex_y"]) == FAR_FROM_THEATER and wonder["adjacency"] == 0
    assert (holy_site["kind"], holy_site["hex_x"], holy_site["hex_y"]) == ("DISTRICT_HOLY_SITE", 10, 9)
    message = {
        "type": "recommendations", "schema_version": 1, "turn": 1, "generated_at": "x",
        "snapshot": {}, "milestones": [], "strategies": [], "actions": [], "cities": [city],
    }
    assert contracts.first_error("recommendations", message) is None
