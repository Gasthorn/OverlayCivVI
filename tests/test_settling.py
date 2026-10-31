"""Sites de colonisation (spec 02 §9) : grille, filtrage, score, règle et message."""

from __future__ import annotations

import copy

import contracts
from conftest import state_from
from engine.game_db import GameDb
from engine.rules.settle_site import SettleSite
from engine.settling import MIN_CITY_DISTANCE, HexGrid, settle_message, settle_sites

WIDTH, HEIGHT = 60, 40


def settle_state(state_dict: dict, tiles: dict[tuple[int, int], dict] | None = None, radius: int = 8) -> dict:
    """Prairie révélée autour des villes du joueur, complétée par `tiles`."""
    data = copy.deepcopy(state_dict)
    grid = HexGrid(WIDTH, HEIGHT)
    centers = [(c["hex_x"], c["hex_y"]) for c in data["cities"]]
    cells = {}
    for x in range(WIDTH):
        for y in range(HEIGHT):
            if any(grid.distance((x, y), c) <= radius for c in centers):
                cell = {"hex_x": x, "hex_y": y, "terrain": "TERRAIN_GRASS"}
                if (x, y) in centers:
                    cell |= {"city": "self", "owner": "self"}
                cells[(x, y)] = cell
    for xy, extra in (tiles or {}).items():
        cells.setdefault(xy, {"hex_x": xy[0], "hex_y": xy[1], "terrain": "TERRAIN_GRASS"}).update(extra)
    data["settle_map"] = {"map_width": WIDTH, "map_height": HEIGHT, "tiles": list(cells.values())}
    return data


def pella(state_dict: dict) -> tuple[int, int]:
    city = state_dict["cities"][0]
    return city["hex_x"], city["hex_y"]


def test_hex_grid_distance_and_wrap() -> None:
    grid = HexGrid(WIDTH, HEIGHT)
    for n in grid.neighbors(10, 10) + grid.neighbors(10, 11):
        assert grid.distance((10, 10), n) <= 1 or grid.distance((10, 11), n) <= 1
    assert all(grid.distance((10, 11), n) == 1 for n in grid.neighbors(10, 11))
    assert grid.distance((0, 5), (WIDTH - 1, 5)) == 1  # la carte boucle d'est en ouest
    assert grid.distance((10, 10), (14, 10)) == 4


def test_sites_respect_city_spacing(game_db: GameDb, mvp1_state_dict: dict) -> None:
    state = state_from(settle_state(mvp1_state_dict))
    grid = HexGrid(WIDTH, HEIGHT)
    sites = settle_sites(state, game_db)
    cities = [(c.hex_x, c.hex_y) for c in state.cities]
    assert sites
    for site in sites:
        xy = (site.hex_x, site.hex_y)
        assert all(grid.distance(xy, c) >= MIN_CITY_DISTANCE for c in cities)
        assert min(grid.distance(xy, c) for c in cities) <= 6
    for a in sites:
        for b in sites:
            if a is not b:
                assert grid.distance((a.hex_x, a.hex_y), (b.hex_x, b.hex_y)) >= MIN_CITY_DISTANCE


def test_fresh_water_luxury_and_natural_wonder_win(game_db: GameDb, mvp1_state_dict: dict) -> None:
    x, y = pella(mvp1_state_dict)
    good = (x, y - 5)
    tiles = {
        good: {"river": True, "terrain": "TERRAIN_GRASS_HILLS"},
        (good[0] + 1, good[1]): {"resource": "RESOURCE_DYES"},
        (good[0] - 2, good[1]): {"natural_wonder": True, "feature": "FEATURE_BARRIER_REEF"},
    }
    state = state_from(settle_state(mvp1_state_dict, tiles))
    best = settle_sites(state, game_db)[0]
    assert (best.hex_x, best.hex_y) == good
    reasons = best.reasons(10)
    assert "eau douce (rivière, lac ou oasis)" in reasons and "sur une colline (défense, production)" in reasons
    assert any(r.startswith("1 luxe (") for r in reasons)
    assert "merveille naturelle à proximité" in reasons


def test_foreign_city_nearby_is_penalized(game_db: GameDb, mvp1_state_dict: dict) -> None:
    x, y = pella(mvp1_state_dict)
    spot = (x, y - 5)
    base = settle_state(mvp1_state_dict, {spot: {"river": True}})
    best = settle_sites(state_from(base), game_db)[0]
    assert (best.hex_x, best.hex_y) == spot
    hostile = settle_state(mvp1_state_dict, {spot: {"river": True}, (x, y - 9): {"city": "other", "owner": "other"}})
    site = next(s for s in settle_sites(state_from(hostile), game_db, limit=50) if (s.hex_x, s.hex_y) == spot)
    assert site.score < best.score and any("ville étrangère à 4 tuiles" in r for r in site.reasons(10))


def test_no_site_on_water_mountain_or_foreign_land(game_db: GameDb, mvp1_state_dict: dict) -> None:
    x, y = pella(mvp1_state_dict)
    blocked = {
        (x + 5, y): {"terrain": "TERRAIN_COAST"},
        (x - 5, y): {"terrain": "TERRAIN_GRASS_MOUNTAIN"},
        (x, y + 5): {"owner": "other"},
    }
    sites = settle_sites(state_from(settle_state(mvp1_state_dict, blocked)), game_db, limit=200)
    assert not {(s.hex_x, s.hex_y) for s in sites} & set(blocked)


def test_settle_message_and_rule(game_db: GameDb, mvp1_state_dict: dict) -> None:
    data = settle_state(mvp1_state_dict)
    state = state_from(data)
    settle = settle_message(state, game_db)
    assert [s["rank"] for s in settle["sites"]] == list(range(1, len(settle["sites"]) + 1))
    message = {
        "type": "recommendations", "schema_version": 1, "turn": 1, "generated_at": "x",
        "snapshot": {}, "milestones": [], "strategies": [], "actions": [], "settle": settle,
    }
    assert contracts.first_error("recommendations", message) is None

    assert SettleSite().evaluate(state, game_db) == []  # aucun colon
    data["units"].append({"unit_id": 7, "type": "UNIT_SETTLER", "hex_x": 1, "hex_y": 1})
    (action,) = SettleSite().evaluate(state_from(data), game_db)
    assert action.title == "Fonder une ville sur le site n°1 (page Colonisation)" and action.priority == 76
