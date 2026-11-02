"""Scores de stratégie (spec 02 §6) sur la partie macédonienne (tour 15) et la vraie partie Kongo (tour 50)."""

from __future__ import annotations

import json

import contracts
from conftest import FIXTURES, state_from
from engine.game_db import GameDb
from engine.strategies import score_strategies


def scores(data: dict, db: GameDb) -> dict[str, dict]:
    return {s["id"]: s for s in score_strategies(state_from(data), db)}


def real_t050() -> dict:
    return json.loads((FIXTURES / "game_state_real_t050.json").read_text(encoding="utf-8"))


def test_early_macedon_favors_cavalry(game_db: GameDb, mvp1_state_dict: dict) -> None:
    result = score_strategies(state_from(mvp1_state_dict), game_db)
    assert [s["id"] for s in result] == [
        "cavalry_rush", "commercial_hub_rush", "science_campus",
        "religious_victory", "naval_warfare", "culture_victory", "medieval_army",
    ]
    cavalry = result[0]
    assert cavalry["score"] == 0.53
    assert cavalry["factors"] == [
        "1 cheval près de vos villes",
        "Voisin rencontré : Grèce",
        "À 2 technologies d'Équitation",
        "Tour 15 : fenêtre d'attaque favorable",
    ]


def test_real_kongo_turn_50_favors_science(game_db: GameDb) -> None:
    result = scores(real_t050(), game_db)
    assert result["science_campus"]["score"] == 0.78
    assert result["science_campus"]["factors"][0] == "8 montagnes et 31 jungles près de vos villes"
    # Vitesse En ligne : tour 50 = tour 100 normalisé, le rush n'a plus de sens.
    assert result["cavalry_rush"]["score"] == 0.26
    assert result["cavalry_rush"]["factors"][0] == "Tour 50 : fenêtre d'attaque qui se referme"


def test_timing_uses_normalized_turn(game_db: GameDb, mvp1_state_dict: dict) -> None:
    standard = scores(mvp1_state_dict, game_db)["cavalry_rush"]["score"]
    mvp1_state_dict["game"]["turn"] = 40
    mvp1_state_dict["game"]["game_speed"] = "GAMESPEED_MARATHON"  # tour 40 = tour 13 normalisé
    assert scores(mvp1_state_dict, game_db)["cavalry_rush"]["score"] == standard
    mvp1_state_dict["game"]["game_speed"] = "GAMESPEED_ONLINE"  # tour 40 = tour 80 normalisé
    assert scores(mvp1_state_dict, game_db)["cavalry_rush"]["score"] < standard / 2


def test_war_target_listed_first(game_db: GameDb, mvp1_state_dict: dict) -> None:
    mvp1_state_dict["known_players"].append(
        {"player_id": 3, "civilization": "CIVILIZATION_BABYLON_STK", "leader": "LEADER_X", "name": "Babylone", "at_war": True}
    )
    factors = scores(mvp1_state_dict, game_db)["cavalry_rush"]["factors"]
    assert "En guerre contre Babylone" in factors


def test_rivers_feed_commercial_hub(game_db: GameDb, mvp1_state_dict: dict) -> None:
    before = scores(mvp1_state_dict, game_db)["commercial_hub_rush"]["score"]
    for tile in mvp1_state_dict["tiles"][:3]:
        tile["river"] = True
    after = scores(mvp1_state_dict, game_db)["commercial_hub_rush"]
    assert after["score"] > before
    assert "3 tuiles de rivière près de vos villes" in after["factors"]


def test_foreign_tiles_ignored(game_db: GameDb, mvp1_state_dict: dict) -> None:
    for tile in mvp1_state_dict["tiles"]:
        tile["owner"] = "other"
    factors = scores(mvp1_state_dict, game_db)["cavalry_rush"]["factors"]
    assert not any("cheval" in f for f in factors)


def test_unique_cavalry_bonus(game_db: GameDb, mvp1_state_dict: dict) -> None:
    mvp1_state_dict["player"]["civilization"] = "CIVILIZATION_ARABIA"  # Mamelouk (remplace le Chevalier)
    factors = scores(mvp1_state_dict, game_db)["cavalry_rush"]["factors"]
    assert any(f.startswith("Bonus unique : ") for f in factors)


def test_strategies_match_contract(game_db: GameDb, mvp1_state_dict: dict) -> None:
    message = {
        "type": "recommendations", "schema_version": 2, "turn": 1, "generated_at": "x",
        "snapshot": {}, "actions": [],
        "strategies": score_strategies(state_from(mvp1_state_dict), game_db),
    }
    assert contracts.first_error("recommendations", message) is None


def test_minimal_state_scores_without_error(game_db: GameDb, mvp0_state: dict) -> None:
    result = score_strategies(state_from(mvp0_state), game_db)
    assert len(result) == 7
    assert all(0 <= s["score"] <= 1 for s in result)


# --- Nouvelles stratégies ------------------------------------------------------

def test_real_kongo_suits_medieval_army(game_db: GameDb) -> None:
    medieval = scores(real_t050(), game_db)["medieval_army"]
    assert medieval["score"] == 0.80
    assert medieval["factors"][0] == "2 gisements de fer près de vos villes, 34 unités de fer en réserve"
    assert "Bonus unique : Ngao Mbeba" in medieval["factors"]


def test_medieval_window_too_early(game_db: GameDb, mvp1_state_dict: dict) -> None:
    factors = scores(mvp1_state_dict, game_db)["medieval_army"]["factors"]
    assert factors[0] == "Tour 15 : Moyen Âge encore lointain"


def test_religion_founded_boosts_religious_victory(game_db: GameDb, mvp1_state_dict: dict) -> None:
    before = scores(mvp1_state_dict, game_db)["religious_victory"]
    assert "Pas encore de religion fondée" in before["factors"]
    mvp1_state_dict["player"]["religion"] = "RELIGION_ORTHODOXY"
    after = scores(mvp1_state_dict, game_db)["religious_victory"]
    assert after["score"] > before["score"]
    assert after["factors"][0].startswith("Religion fondée : ")


def test_culture_counts_wonders_and_civic_progress(game_db: GameDb) -> None:
    factors = scores(real_t050(), game_db)["culture_victory"]["factors"]
    assert "1 ville avec merveille" in factors
    assert any(f.endswith("disponible") for f in factors)  # Art dramatique et poésie (dogme)


def test_site_factor_uses_game_adjacency(game_db: GameDb) -> None:
    data = real_t050()
    for city in data["cities"]:
        city["district_sites"] = {}
    data["cities"][3]["district_sites"] = {"DISTRICT_CAMPUS": {"adjacency": 4, "hex_x": 1, "hex_y": 1}}  # Kwango
    data["cities"][5]["district_sites"] = {"DISTRICT_CAMPUS": {"adjacency": 2, "hex_x": 2, "hex_y": 2}}  # Bukavu
    science = scores(data, game_db)["science_campus"]
    assert "Meilleur emplacement de Campus : +4 à Kwango" in science["factors"]
    assert not any("montagnes" in f for f in science["factors"])  # l'estimation n'est plus utilisée


def test_naval_warfare_needs_coastal_cities(game_db: GameDb) -> None:
    data = real_t050()
    unknown = scores(data, game_db)["naval_warfare"]
    assert unknown["score"] == 0.36  # côtes inconnues (export antérieur au champ) : pas de pénalité
    for city in data["cities"]:
        city["coastal"] = False
    landlocked = scores(data, game_db)["naval_warfare"]
    assert landlocked["factors"][0] == "Aucune ville côtière"
    assert landlocked["score"] < unknown["score"] / 2
    data["cities"][0]["coastal"] = data["cities"][2]["coastal"] = True
    coastal = scores(data, game_db)["naval_warfare"]
    assert landlocked["score"] < coastal["score"] < unknown["score"]
    assert "2 villes côtières sur 6" in coastal["factors"]
