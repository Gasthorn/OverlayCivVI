"""Règles du MVP 1 (spec 02 §5.2), sur une partie macédonienne au tour 15 et la vraie base du jeu."""

from __future__ import annotations

import copy
import json

import pytest

import contracts
from conftest import FIXTURES, state_from
from engine.game_db import GameDb
from engine.rules import Action, run_rules
from engine.rules.boosted_available import BoostedAvailable
from engine.rules.eureka_reachable import EurekaReachable
from engine.rules.housing_cap import HousingCap
from engine.rules.idle_city import IdleCity
from engine.rules.idle_research import IdleResearch
from engine.rules.unlock_visible_resource import UnlockVisibleResource


def by_id(actions: list[Action]) -> dict[str, Action]:
    return {a.id: a for a in actions}


# --- idle_research -----------------------------------------------------------

def test_idle_civic_detected(game_db: GameDb, mvp1_state_dict: dict) -> None:
    actions = by_id(IdleResearch().evaluate(state_from(mvp1_state_dict), game_db))
    assert set(actions) == {"idle_research:civic"}
    assert actions["idle_research:civic"].priority == 90


def test_idle_research_detected(game_db: GameDb, mvp1_state_dict: dict) -> None:
    mvp1_state_dict["techs"]["current_research"] = None
    assert "idle_research:tech" in by_id(IdleResearch().evaluate(state_from(mvp1_state_dict), game_db))


def test_idle_civic_ignored_without_civics_section(game_db: GameDb, mvp1_state_dict: dict) -> None:
    del mvp1_state_dict["civics"]
    assert IdleResearch().evaluate(state_from(mvp1_state_dict), game_db) == []


# --- boosted_available -------------------------------------------------------

def test_boosted_tech_recommended(game_db: GameDb, mvp1_state_dict: dict) -> None:
    (action,) = BoostedAvailable().evaluate(state_from(mvp1_state_dict), game_db)
    assert action.title == "Rechercher Tir à l'arc"
    assert action.reason == "Eurêka déjà obtenu : −40 % du coût"
    assert action.target_type == "TECH_ARCHERY"


def test_boosted_tech_not_recommended_when_already_current(game_db: GameDb, mvp1_state_dict: dict) -> None:
    mvp1_state_dict["techs"]["current_research"] = "TECH_ARCHERY"
    assert BoostedAvailable().evaluate(state_from(mvp1_state_dict), game_db) == []


def test_boosted_tech_with_missing_prereq_ignored(game_db: GameDb, mvp1_state_dict: dict) -> None:
    mvp1_state_dict["techs"]["boosted"] = ["TECH_HORSEBACK_RIDING"]
    assert BoostedAvailable().evaluate(state_from(mvp1_state_dict), game_db) == []


# --- eureka_reachable --------------------------------------------------------

def test_eureka_by_owning_a_unit(game_db: GameDb, mvp1_state_dict: dict) -> None:
    actions = by_id(EurekaReachable().evaluate(state_from(mvp1_state_dict), game_db))
    action = actions["eureka_reachable:CIVIC_FOREIGN_TRADE"]
    assert action.title == "Produire Éclaireur"
    assert action.reason == "Déclenche l'Inspiration de Commerce avec l'étranger (−40 %)"
    assert action.category == "production"


def test_eureka_by_improvement(game_db: GameDb, mvp1_state_dict: dict) -> None:
    actions = by_id(EurekaReachable().evaluate(state_from(mvp1_state_dict), game_db))
    assert actions["eureka_reachable:TECH_MASONRY"].title == "Aménager Carrière"
    assert actions["eureka_reachable:TECH_IRRIGATION"].title == "Aménager Ferme"
    assert actions["eureka_reachable:TECH_IRRIGATION"].reason == "Déclenche l'Eurêka d'Irrigation (−40 %)"


def test_eureka_already_met_is_not_recommended(game_db: GameDb, mvp1_state_dict: dict) -> None:
    mvp1_state_dict["units"].append({"unit_id": 3, "type": "UNIT_SCOUT", "hex_x": 1, "hex_y": 1})
    mvp1_state_dict["tiles"][4]["improvement"] = "IMPROVEMENT_QUARRY"
    actions = by_id(EurekaReachable().evaluate(state_from(mvp1_state_dict), game_db))
    assert "eureka_reachable:CIVIC_FOREIGN_TRADE" not in actions
    assert "eureka_reachable:TECH_MASONRY" not in actions


def test_eureka_needs_unlocked_improvement(game_db: GameDb, mvp1_state_dict: dict) -> None:
    # Équitation (1 pâturage) n'est pas disponible sans Tir à l'arc ; avec, le pâturage est déjà débloqué.
    mvp1_state_dict["techs"]["researched"].append("TECH_ARCHERY")
    actions = by_id(EurekaReachable().evaluate(state_from(mvp1_state_dict), game_db))
    assert actions["eureka_reachable:TECH_HORSEBACK_RIDING"].title == "Aménager Pâturage"

    mvp1_state_dict["techs"]["researched"].remove("TECH_ANIMAL_HUSBANDRY")
    actions = by_id(EurekaReachable().evaluate(state_from(mvp1_state_dict), game_db))
    assert "eureka_reachable:TECH_HORSEBACK_RIDING" not in actions


def test_naval_eureka_requires_coastal_city(game_db: GameDb) -> None:
    """Vrai tour 50 (Kongo) : Construction navale demande 2 galères."""
    data = json.loads((FIXTURES / "game_state_real_t050.json").read_text(encoding="utf-8"))
    key = "eureka_reachable:TECH_SHIPBUILDING"

    for city in data["cities"]:
        city["coastal"] = False
    assert key not in by_id(EurekaReachable().evaluate(state_from(data), game_db))

    data["cities"][4]["coastal"] = True  # Mbanza Mpangu
    assert by_id(EurekaReachable().evaluate(state_from(data), game_db))[key].title == "Produire 2 × Galère"


def test_eureka_unsupported_boost_class_ignored(game_db: GameDb, mvp1_state_dict: dict) -> None:
    actions = by_id(EurekaReachable().evaluate(state_from(mvp1_state_dict), game_db))
    assert "eureka_reachable:TECH_BRONZE_WORKING" not in actions  # tuer 3 barbares


# --- idle_city ---------------------------------------------------------------

def test_idle_city(game_db: GameDb, mvp1_state_dict: dict) -> None:
    (action,) = IdleCity().evaluate(state_from(mvp1_state_dict), game_db)
    assert action.title == "Choisir une production à Pella"
    assert action.city_id == 65536


# --- housing_cap -------------------------------------------------------------

def test_housing_cap_suggests_granary(game_db: GameDb, mvp1_state_dict: dict) -> None:
    (action,) = HousingCap().evaluate(state_from(mvp1_state_dict), game_db)
    assert action.title == "Construire Grenier à Pella"
    assert action.reason == "Population 3 / logement 3.5 : la croissance ralentit"
    assert action.priority == 50


def test_housing_cap_saturated_without_granary_option(game_db: GameDb, mvp1_state_dict: dict) -> None:
    city = mvp1_state_dict["cities"][0]
    city["population"], city["buildings"] = 4, ["BUILDING_PALACE", "BUILDING_GRANARY"]
    (action,) = HousingCap().evaluate(state_from(mvp1_state_dict), game_db)
    assert action.title == "Augmenter le logement à Pella"
    assert action.priority == 65
    assert "très ralentie" in action.reason


# --- unlock_visible_resource -------------------------------------------------

def test_unlock_visible_resource(game_db: GameDb, mvp1_state_dict: dict) -> None:
    (action,) = UnlockVisibleResource().evaluate(state_from(mvp1_state_dict), game_db)
    assert action.target_type == "TECH_IRRIGATION"
    assert action.title == "Rechercher Irrigation"
    # Le coton de la tuile étrangère est ignoré ; chevaux et pierre sont déjà aménageables.
    assert action.reason == "Permet d'aménager 2 ressources près de vos villes : Coton ×2"


# --- run_rules ---------------------------------------------------------------

def test_run_rules_merges_and_sorts(game_db: GameDb, mvp1_state_dict: dict) -> None:
    actions = run_rules(state_from(mvp1_state_dict), game_db)
    priorities = [a.priority for a in actions]
    assert priorities == sorted(priorities, reverse=True)
    assert actions[0].id == "idle_research:civic"
    for action in actions:
        assert contracts.first_error("recommendations", {
            "type": "recommendations", "schema_version": 2, "turn": 1, "generated_at": "x",
            "snapshot": {}, "strategies": [], "actions": [action.to_message()],
        }) is None


def test_run_rules_merges_same_target(game_db: GameDb, mvp1_state_dict: dict) -> None:
    # Tir à l'arc boosté + coton : deux règles ciblent des techs différentes ; on force un doublon.
    mvp1_state_dict["techs"]["boosted"] = ["TECH_IRRIGATION"]
    actions = by_id(run_rules(state_from(mvp1_state_dict), game_db))
    merged = [a for a in actions.values() if a.target_type == "TECH_IRRIGATION" and a.category == "research"]
    assert len(merged) == 1
    assert "Eurêka déjà obtenu" in merged[0].reason and "Coton" in merged[0].reason
    assert merged[0].priority == 75


def test_failing_rule_does_not_break_others(game_db: GameDb, mvp1_state_dict: dict) -> None:
    class Broken:
        id = "broken"

        def evaluate(self, state, db):
            raise RuntimeError("boom")

    actions = run_rules(state_from(mvp1_state_dict), game_db, [Broken(), IdleCity()])
    assert [a.id for a in actions] == ["idle_city:65536"]


@pytest.mark.parametrize("rule", [IdleResearch(), BoostedAvailable(), EurekaReachable(), IdleCity(), HousingCap(), UnlockVisibleResource()])
def test_rules_handle_mvp0_state(game_db: GameDb, mvp0_state: dict, rule) -> None:
    """Un état minimal (sans villes, tuiles ni dogmes) ne fait planter aucune règle."""
    rule.evaluate(state_from(copy.deepcopy(mvp0_state)), game_db)
