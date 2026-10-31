"""Disposition des quartiers (spec 02 §7) : règles d'interaction, recherche, grille, messages."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import contracts
from city_map import hex_patch, neighbor_coords, ring1
from conftest import FIXTURES, state_from
from engine.city_layout import CityPlotsCache, city_layouts, odd_rows_shifted, plan_layout, strategy_weights
from engine.game_db import GameDb
from engine.state import CityPlot

CENTER = (10, 10)


def plots_of(raw: list[dict]) -> tuple[CityPlot, ...]:
    from engine.state import _parse_city

    return _parse_city({"city_id": 1, "name": "X", "hex_x": 0, "hex_y": 0, "population": 1, "plots": raw}).plots


def with_city_plots(state_dict: dict, raw_plots: list[dict], slots: dict | None = None) -> dict:
    data = copy.deepcopy(state_dict)
    data["cities"][0]["plots"] = raw_plots
    if slots is not None:
        data["cities"][0]["district_slots"] = slots
    return data


def with_techs(data: dict, *techs: str) -> dict:
    data["techs"]["researched"] = data["techs"]["researched"] + list(techs)
    return data


# --- Règles d'interaction (base réelle, BBG compris) ------------------------------------

def test_harbor_boosts_commercial_hub(game_db: GameDb) -> None:
    # Harbor_Gold (+2) + District_Gold (+1 pour 2 quartiers voisins).
    assert game_db.district_interaction("DISTRICT_COMMERCIAL_HUB", "DISTRICT_HARBOR", set(), set(), set()) == 2.5


def test_generic_neighbor_bonus(game_db: GameDb) -> None:
    assert game_db.district_interaction("DISTRICT_CAMPUS", "DISTRICT_THEATER", set(), set(), set()) == 0.5


def test_excluded_adjacency_for_trait(game_db: GameDb) -> None:
    # Les Gaulois n'ont pas le bonus « quartiers voisins » pour le Campus.
    traits = game_db.player_traits("CIVILIZATION_GAUL", "LEADER_AMBIORIX")
    assert game_db.district_interaction("DISTRICT_CAMPUS", "DISTRICT_THEATER", traits, set(), set()) == 0


# --- Grille ------------------------------------------------------------------------------

def test_grid_convention_inferred_from_neighbors() -> None:
    assert odd_rows_shifted(plots_of(hex_patch(CENTER, ring1(CENTER), odd_shifted=True))) is True
    assert odd_rows_shifted(plots_of(hex_patch(CENTER, ring1(CENTER, False), odd_shifted=False))) is False


# --- Recherche de disposition ----------------------------------------------------------------

def test_commercial_hub_goes_next_to_harbor(game_db: GameDb, mvp1_state_dict: dict) -> None:
    """Seule, la plateforme irait sur A (+2) ; à côté du port (B, +1 de base), elle vaut +3,5."""
    owned = ring1(CENTER) | {(12, 10), (8, 10)}
    a, b, coast = (12, 10), (9, 10), (8, 10)
    assert coast in neighbor_coords(*b)
    tiles = {
        a: {"sites": {"DISTRICT_COMMERCIAL_HUB": 2}},
        b: {"sites": {"DISTRICT_COMMERCIAL_HUB": 1}},
        coast: {"terrain": "TERRAIN_COAST", "sites": {"DISTRICT_HARBOR": 0}},
    }
    state = state_from(mvp1_state_dict)
    placements = {p.district: p for p in plan_layout(plots_of(hex_patch(CENTER, owned, tiles)), game_db, state)}
    by_index = {p.index: (p.hex_x, p.hex_y) for p in plots_of(hex_patch(CENTER, owned, tiles))}

    assert by_index[placements["DISTRICT_COMMERCIAL_HUB"].plot] == b
    assert placements["DISTRICT_COMMERCIAL_HUB"].adjacency == 3.5
    assert by_index[placements["DISTRICT_HARBOR"].plot] == coast


def test_each_plot_hosts_one_district(game_db: GameDb, mvp1_state_dict: dict) -> None:
    owned = ring1(CENTER)
    tiles = {c: {"sites": {"DISTRICT_CAMPUS": 3, "DISTRICT_THEATER": 2}} for c in owned}
    placements = plan_layout(plots_of(hex_patch(CENTER, owned, tiles)), game_db, state_from(mvp1_state_dict))
    assert sorted(p.district for p in placements) == ["DISTRICT_CAMPUS", "DISTRICT_THEATER"]
    assert len({p.plot for p in placements}) == 2


def test_unique_district_replaces_generic(game_db: GameDb, mvp1_state_dict: dict) -> None:
    owned = ring1(CENTER)
    tiles = {c: {"sites": {"DISTRICT_CAMPUS": 1, "DISTRICT_SEOWON": 4}} for c in owned}
    raw = hex_patch(CENTER, owned, tiles)

    # La Corée construit le Seowon à la place du Campus…
    mvp1_state_dict["player"].update(civilization="CIVILIZATION_KOREA", leader="LEADER_SEONDEOK")
    placements = plan_layout(plots_of(raw), game_db, state_from(mvp1_state_dict))
    assert [p.district for p in placements] == ["DISTRICT_SEOWON"]

    # …la Macédoine n'y a pas accès : Campus ordinaire.
    mvp1_state_dict["player"].update(civilization="CIVILIZATION_MACEDON", leader="LEADER_JFD_OLYMPIAS")
    placements = plan_layout(plots_of(raw), game_db, state_from(mvp1_state_dict))
    assert [p.district for p in placements] == ["DISTRICT_CAMPUS"]


def test_followed_strategy_wins_contested_tile(game_db: GameDb, mvp1_state_dict: dict) -> None:
    """Campus et Lieu saint ont la même meilleure case : la stratégie suivie tranche."""
    owned = ring1(CENTER)
    best, other = (11, 10), (9, 10)
    tiles = {
        best: {"sites": {"DISTRICT_CAMPUS": 3, "DISTRICT_HOLY_SITE": 3}},
        other: {"sites": {"DISTRICT_CAMPUS": 1, "DISTRICT_HOLY_SITE": 1}},
    }
    raw = hex_patch(CENTER, owned, tiles)
    by_index = {p["index"]: (p["hex_x"], p["hex_y"]) for p in raw}
    state = state_from(mvp1_state_dict)

    def tile_of(followed: str) -> dict[str, tuple[int, int]]:
        placements = plan_layout(plots_of(raw), game_db, state, strategy_weights(followed))
        return {p.district: by_index[p.plot] for p in placements}

    assert tile_of("science_campus")["DISTRICT_CAMPUS"] == best
    assert tile_of("religious_victory")["DISTRICT_HOLY_SITE"] == best


def test_industrial_zone_goes_next_to_aqueduct(game_db: GameDb, mvp1_state_dict: dict) -> None:
    """Aqueduc prévu : la Zone industrielle se place à côté (+2), pas sur la case à +1 isolée."""
    owned = ring1(CENTER) | {(12, 10), (13, 10)}
    near, far = (12, 10), (9, 11)
    aqueduct = (11, 10)
    assert aqueduct in neighbor_coords(*near) and aqueduct not in neighbor_coords(*far)
    tiles = {
        aqueduct: {"sites": {"DISTRICT_AQUEDUCT": 0}},
        near: {"sites": {"DISTRICT_INDUSTRIAL_ZONE": 0}},
        far: {"sites": {"DISTRICT_INDUSTRIAL_ZONE": 1}},
    }
    raw = hex_patch(CENTER, owned, tiles)
    by_index = {p["index"]: (p["hex_x"], p["hex_y"]) for p in raw}
    placements = {p.district: p for p in plan_layout(plots_of(raw), game_db, state_from(mvp1_state_dict))}
    assert by_index[placements["DISTRICT_INDUSTRIAL_ZONE"].plot] == near
    assert placements["DISTRICT_INDUSTRIAL_ZONE"].adjacency == 2.5  # Aqueduc +2, quartier voisin +0,5


def test_unbought_tiles_used_but_not_foreign_ones(game_db: GameDb, mvp1_state_dict: dict) -> None:
    owned = ring1(CENTER)
    unbought, foreign = (12, 10), (8, 10)
    tiles = {
        unbought: {"owned": False, "sites": {"DISTRICT_CAMPUS": 3}},
        foreign: {"owned": False, "foreign": True, "sites": {"DISTRICT_CAMPUS": 9}},
        (11, 10): {"sites": {"DISTRICT_CAMPUS": 1}},
    }
    raw = hex_patch(CENTER, owned | {unbought, foreign}, tiles)
    by_index = {p["index"]: (p["hex_x"], p["hex_y"]) for p in raw}
    (placement,) = plan_layout(plots_of(raw), game_db, state_from(mvp1_state_dict))
    assert by_index[placement.plot] == unbought


def test_support_districts_do_not_use_slots(game_db: GameDb, mvp1_state_dict: dict) -> None:
    owned = ring1(CENTER)
    coords = sorted(owned)
    tiles = {coords[0]: {"sites": {"DISTRICT_CAMPUS": 2}}, coords[3]: {"sites": {"DISTRICT_AQUEDUCT": 0}}}
    data = with_city_plots(mvp1_state_dict, hex_patch(CENTER, owned, tiles), slots={"used": 1, "allowed": 1})
    state = state_from(with_techs(data, "TECH_WRITING", "TECH_ENGINEERING"))
    (city,) = city_layouts(state, game_db, CityPlotsCache().update("g", state), "science_campus")
    entries = {e["kind"]: e for e in city["layout"]}
    assert (entries["DISTRICT_CAMPUS"]["status"], entries["DISTRICT_CAMPUS"]["focus"]) == ("later", True)
    assert (entries["DISTRICT_AQUEDUCT"]["status"], entries["DISTRICT_AQUEDUCT"]["uses_slot"]) == ("now", False)


def test_cache_restores_best_sites_between_turn_begins(mvp1_state_dict: dict) -> None:
    cache = CityPlotsCache()
    begin = copy.deepcopy(mvp1_state_dict)
    begin["cities"][0]["district_sites"] = {"DISTRICT_CAMPUS": {"adjacency": 3, "hex_x": 1, "hex_y": 1}}
    cache.update("g", state_from(begin))

    changed = cache.enrich(state_from(mvp1_state_dict))  # state_changed : rien d'exporté
    assert changed.cities[0].district_sites["DISTRICT_CAMPUS"].adjacency == 3
    assert changed.cities[1].district_sites is None


def test_luxury_and_strategic_resources_are_never_covered(game_db: GameDb, mvp1_state_dict: dict) -> None:
    owned = ring1(CENTER)
    luxury, strategic, artifact, empty = (11, 10), (9, 10), (10, 9), (10, 11)
    tiles = {
        luxury: {"resource": "RESOURCE_DYES", "sites": {"DISTRICT_CAMPUS": 6}},
        strategic: {"resource": "RESOURCE_IRON", "sites": {"DISTRICT_CAMPUS": 5}},
        artifact: {"resource": "RESOURCE_ANTIQUITY_SITE", "sites": {"DISTRICT_CAMPUS": 5}},
        empty: {"sites": {"DISTRICT_CAMPUS": 1}},
    }
    raw = hex_patch(CENTER, owned, tiles)
    by_index = {p["index"]: (p["hex_x"], p["hex_y"]) for p in raw}
    (placement,) = plan_layout(plots_of(raw), game_db, state_from(mvp1_state_dict))
    assert by_index[placement.plot] == empty


def test_bonus_resource_tile_only_when_clearly_better(game_db: GameDb, mvp1_state_dict: dict) -> None:
    owned = ring1(CENTER)
    wheat, empty = (11, 10), (9, 10)

    def chosen(wheat_adjacency: float) -> tuple[int, int]:
        tiles = {
            wheat: {"resource": "RESOURCE_WHEAT", "sites": {"DISTRICT_CAMPUS": wheat_adjacency}},
            empty: {"sites": {"DISTRICT_CAMPUS": 2}},
        }
        raw = hex_patch(CENTER, owned, tiles)
        by_index = {p["index"]: (p["hex_x"], p["hex_y"]) for p in raw}
        (placement,) = plan_layout(plots_of(raw), game_db, state_from(mvp1_state_dict))
        return by_index[placement.plot]

    assert chosen(2) == empty   # à égalité, on garde le blé
    assert chosen(4) == wheat   # nettement mieux : le blé est sacrifié


def test_best_sites_recomputed_without_protected_resources(game_db: GameDb, mvp1_state_dict: dict) -> None:
    owned = ring1(CENTER)
    tiles = {
        (11, 10): {"resource": "RESOURCE_DYES", "sites": {"DISTRICT_CAMPUS": 6}},
        (9, 10): {"sites": {"DISTRICT_CAMPUS": 2}},
    }
    data = with_city_plots(mvp1_state_dict, hex_patch(CENTER, owned, tiles))
    # Le mod, lui, désigne la tuile de teinture comme meilleur emplacement.
    data["cities"][0]["district_sites"] = {"DISTRICT_CAMPUS": {"adjacency": 6, "hex_x": 11, "hex_y": 10}}
    cache = CityPlotsCache()
    cache.update("g", state_from(data), game_db)
    site = cache.enrich(state_from(data)).cities[0].district_sites["DISTRICT_CAMPUS"]
    assert (site.hex_x, site.hex_y, site.adjacency) == (9, 10, 2)


def test_tiles_carry_resource_kind(game_db: GameDb, mvp1_state_dict: dict) -> None:
    owned = ring1(CENTER)
    tiles = {(11, 10): {"resource": "RESOURCE_DYES"}, (9, 10): {"resource": "RESOURCE_WHEAT"}}
    data = with_city_plots(mvp1_state_dict, hex_patch(CENTER, owned, tiles))
    state = state_from(data)
    (city,) = city_layouts(state, game_db, CityPlotsCache().update("g", state), None)
    kinds = {(t["hex_x"], t["hex_y"]): t["resource_kind"] for t in city["tiles"] if t["resource"]}
    assert kinds == {(11, 10): "luxury", (9, 10): "bonus"}


def test_foreign_unique_districts_are_ignored(game_db: GameDb) -> None:
    """Partie Kongo : le jeu propose aussi Suguba (Mali), Thanh (Vietnam), Suk Dzong (Bhoutan)."""
    data = json.loads((FIXTURES / "game_state_real_t050.json").read_text(encoding="utf-8"))
    owned = ring1(CENTER)
    sites = {
        "DISTRICT_SUGUBA": 5, "DISTRICT_THANH": 5, "DISTRICT_SUK_DZONG": 5,
        "DISTRICT_COMMERCIAL_HUB": 1, "DISTRICT_ENCAMPMENT": 0, "DISTRICT_HOLY_SITE": 1,
    }
    placements = plan_layout(
        plots_of(hex_patch(CENTER, owned, {c: {"sites": dict(sites)} for c in owned})), game_db, state_from(data),
    )
    assert sorted(p.district for p in placements) == [
        "DISTRICT_COMMERCIAL_HUB", "DISTRICT_ENCAMPMENT", "DISTRICT_HOLY_SITE",
    ]


def test_best_site_ignores_foreign_uniques(game_db: GameDb) -> None:
    from engine.strategy_focus import best_site

    data = json.loads((FIXTURES / "game_state_real_t050.json").read_text(encoding="utf-8"))
    data["cities"][3]["district_sites"] = {
        "DISTRICT_SUGUBA": {"adjacency": 6, "hex_x": 1, "hex_y": 1},
        "DISTRICT_COMMERCIAL_HUB": {"adjacency": 2, "hex_x": 2, "hex_y": 2},
    }
    state = state_from(data)
    traits = game_db.player_traits(state.civilization, state.leader)
    assert best_site(state.cities[3], game_db, "DISTRICT_COMMERCIAL_HUB", traits).adjacency == 2
    # Pour le Mali, c'est la Suguba qui compte.
    mali = game_db.player_traits("CIVILIZATION_MALI", "LEADER_MANSA_MUSA")
    assert best_site(state.cities[3], game_db, "DISTRICT_COMMERCIAL_HUB", mali).adjacency == 6


def test_new_district_counts_its_boost_to_existing_ones(game_db: GameDb, mvp1_state_dict: dict) -> None:
    """Un port à côté d'une plateforme existante rapporte +2,5 à celle-ci : il y est placé."""
    owned = ring1(CENTER) | {(12, 10), (13, 10), (8, 10)}
    tiles = {
        (12, 10): {"district": "DISTRICT_COMMERCIAL_HUB"},
        (13, 10): {"terrain": "TERRAIN_COAST", "sites": {"DISTRICT_HARBOR": 0}},
        (8, 10): {"terrain": "TERRAIN_COAST", "sites": {"DISTRICT_HARBOR": 1}},
    }
    raw = hex_patch(CENTER, owned, tiles)
    by_index = {p["index"]: (p["hex_x"], p["hex_y"]) for p in raw}
    (placement,) = plan_layout(plots_of(raw), game_db, state_from(mvp1_state_dict))
    assert by_index[placement.plot] == (13, 10)


# --- Cache et messages --------------------------------------------------------------------

def test_plots_cache_reuses_last_map(mvp1_state_dict: dict) -> None:
    cache = CityPlotsCache()
    raw = hex_patch(CENTER, ring1(CENTER))
    begin = state_from(with_city_plots(mvp1_state_dict, raw))
    assert set(cache.update("g", begin)) == {65536}

    changed = state_from(mvp1_state_dict)  # state_changed : pas de carte exportée
    assert len(cache.update("g", changed)[65536]) == len(raw)
    assert cache.update("autre-partie", changed) == {}


def test_city_layout_message(game_db: GameDb, mvp1_state_dict: dict) -> None:
    owned = ring1(CENTER)
    tiles = {c: {"sites": {"DISTRICT_CAMPUS": i, "DISTRICT_ENCAMPMENT": 0}} for i, c in enumerate(sorted(owned))}
    data = with_city_plots(mvp1_state_dict, hex_patch(CENTER, owned, tiles), slots={"used": 0, "allowed": 1})
    state = state_from(with_techs(data, "TECH_WRITING", "TECH_BRONZE_WORKING"))
    cities = city_layouts(state, game_db, CityPlotsCache().update("g", state), followed="medieval_army")

    (city,) = cities
    assert city["name"] == "Pella" and city["slots"] == {"used": 0, "allowed": 1}
    # Stratégie suivie : le Campement passe en premier et prend l'unique emplacement libre.
    assert [(e["kind"], e["status"]) for e in city["layout"]] == [
        ("DISTRICT_ENCAMPMENT", "now"), ("DISTRICT_CAMPUS", "later"),
    ]
    # Meilleure tuile (+5) et Campement prévu voisin (+1 pour 2 quartiers voisins).
    assert city["layout"][1]["adjacency"] == 5.5
    centre = next(t for t in city["tiles"] if t["district"] == "DISTRICT_CITY_CENTER")
    assert (centre["x"], centre["y"]) == (10.0, 10.0)
    odd = next(t for t in city["tiles"] if t["hex_y"] == 11)
    assert odd["x"] == odd["hex_x"] + 0.5  # rangée impaire décalée

    message = {
        "type": "recommendations", "schema_version": 1, "turn": 1, "generated_at": "x",
        "snapshot": {}, "milestones": [], "strategies": [], "actions": [], "cities": cities,
    }
    assert contracts.first_error("recommendations", message) is None


def test_locked_districts_are_planned_but_never_now(game_db: GameDb, mvp1_state_dict: dict) -> None:
    owned = ring1(CENTER)
    coords = sorted(owned)
    tiles = {coords[0]: {"sites": {"DISTRICT_CAMPUS": 2}}, coords[3]: {"sites": {"DISTRICT_THEATER": 3}}}
    data = with_city_plots(mvp1_state_dict, hex_patch(CENTER, owned, tiles), slots={"used": 0, "allowed": 2})
    state = state_from(with_techs(data, "TECH_WRITING"))
    (city,) = city_layouts(state, game_db, CityPlotsCache().update("g", state), None)
    # Débloqués d'abord ; la Place du théâtre (Théâtre et poésie manquant) garde sa case, « plus tard ».
    assert [(e["kind"], e["status"], e["unlocked"]) for e in city["layout"]] == [
        ("DISTRICT_CAMPUS", "now", True), ("DISTRICT_THEATER", "later", False),
    ]
    assert city["layout"][1]["requires"] == game_db.name("CIVIC_DRAMA_POETRY")
    assert city["layout"][0]["requires"] is None


def test_one_per_empire_districts_only_in_capital(game_db: GameDb, mvp1_state_dict: dict) -> None:
    from engine.city_layout import excluded_districts

    state = state_from(mvp1_state_dict)
    capital, other = state.cities
    assert "DISTRICT_GOVERNMENT" not in excluded_districts(capital, state, game_db)
    assert "DISTRICT_GOVERNMENT" in excluded_districts(other, state, game_db)
    data = copy.deepcopy(mvp1_state_dict)
    data["cities"][1]["districts"].append("DISTRICT_GOVERNMENT")
    built = state_from(data)
    assert "DISTRICT_GOVERNMENT" in excluded_districts(built.cities[0], built, game_db)


def test_entertainment_complex_and_water_park_are_exclusive(game_db: GameDb, mvp1_state_dict: dict) -> None:
    owned = ring1(CENTER)
    coords = sorted(owned)
    tiles = {
        coords[0]: {"sites": {"DISTRICT_ENTERTAINMENT_COMPLEX": 0}},
        coords[1]: {"sites": {"DISTRICT_WATER_ENTERTAINMENT_COMPLEX": 0}},
    }
    data = with_city_plots(mvp1_state_dict, hex_patch(CENTER, owned, tiles))
    placements = plan_layout(plots_of(data["cities"][0]["plots"]), game_db, state_from(data))
    assert len(placements) == 1


def test_other_city_tiles_are_drawn_but_never_planned(game_db: GameDb, mvp1_state_dict: dict) -> None:
    owned = ring1(CENTER)
    coords = sorted(owned)
    tiles = {
        coords[0]: {"sites": {"DISTRICT_CAMPUS": 5}, "other_city": "Aigai", "district": "DISTRICT_CAMPUS"},
        coords[1]: {"sites": {"DISTRICT_CAMPUS": 1}},
    }
    data = with_techs(with_city_plots(mvp1_state_dict, hex_patch(CENTER, owned, tiles)), "TECH_WRITING")
    state = state_from(data)
    (city,) = city_layouts(state, game_db, CityPlotsCache().update("g", state), None)
    (entry,) = city["layout"]
    assert (entry["hex_x"], entry["hex_y"]) == coords[1]
    other = next(t for t in city["tiles"] if (t["hex_x"], t["hex_y"]) == coords[0])
    assert other["other_city"] == "Aigai" and other["district_label"] == game_db.name("DISTRICT_CAMPUS")


def test_service_publishes_city_layouts(tmp_path: Path, game_db_path: Path, mvp1_state_dict: dict) -> None:
    from test_strategy_focus import make_service

    owned = ring1(CENTER)
    tiles = {c: {"sites": {"DISTRICT_CAMPUS": 2}} for c in owned}
    service, broadcaster = make_service(tmp_path, game_db_path)
    service.handle_payload(json.dumps(with_city_plots(mvp1_state_dict, hex_patch(CENTER, owned, tiles))).encode())
    cities = broadcaster.messages[-1]["cities"]
    assert [c["name"] for c in cities] == ["Pella"]

    # Changement en cours de tour, sans carte : la disposition reste disponible (cache).
    changed = copy.deepcopy(mvp1_state_dict)
    changed["meta"]["trigger"] = "state_changed"
    service.handle_payload(json.dumps(changed).encode())
    assert [c["name"] for c in broadcaster.messages[-1]["cities"]] == ["Pella"]


def test_real_state_without_plots_has_no_city_maps(game_db: GameDb) -> None:
    state = state_from(json.loads((FIXTURES / "game_state_real_t050.json").read_text(encoding="utf-8")))
    assert city_layouts(state, game_db, CityPlotsCache().update("g", state), None) == []
