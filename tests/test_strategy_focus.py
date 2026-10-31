"""Stratégie suivie (spec 02 §6.5) : actions de focus, priorités, persistance et canal overlay → moteur."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from websockets.asyncio.client import connect

import contracts
from conftest import FIXTURES, state_from
from engine.config import EngineConfig
from engine.game_db import GameDb
from engine.preferences import FollowedStrategies
from engine.rules import URGENT_PRIORITY, run_rules
from engine.service import EngineService
from engine.strategy_focus import focus_actions
from engine.ws_server import Broadcaster


def real_t050() -> dict:
    return json.loads((FIXTURES / "game_state_real_t050.json").read_text(encoding="utf-8"))


def titles(actions) -> list[str]:
    return [a.title for a in actions]


# Actions communes à toutes les stratégies (expansion, bâtisseurs, quartiers hors quota).
COMMON_KEYS = (":settlers", ":builders", ":support:")


def plan_actions(state, db: GameDb, strategy_id: str) -> list:
    """Actions propres au plan de la stratégie, sans les actions communes."""
    return [a for a in focus_actions(state, db, strategy_id) if not any(k in a.id for k in COMMON_KEYS)]


# --- Actions de focus ------------------------------------------------------------

def test_science_focus_early_researches_writing(game_db: GameDb, mvp1_state_dict: dict) -> None:
    (action,) = plan_actions(state_from(mvp1_state_dict), game_db, "science_campus")
    assert (action.title, action.reason) == ("Rechercher Écriture", "Focus Scientifique : débloque Campus")
    assert action.strategy == "science_campus"


def test_commercial_focus_walks_prereq_chain(game_db: GameDb, mvp1_state_dict: dict) -> None:
    (action,) = plan_actions(state_from(mvp1_state_dict), game_db, "commercial_hub_rush")
    assert action.title == "Rechercher Écriture"
    assert action.reason == "Rush Commercial : en route vers Monnaie (Plateforme commerciale)"


def test_cavalry_focus_early(game_db: GameDb, mvp1_state_dict: dict) -> None:
    actions = plan_actions(state_from(mvp1_state_dict), game_db, "cavalry_rush")
    assert titles(actions) == ["Rechercher Tir à l'arc", "Aménager Pâturage"]
    assert actions[1].reason == "Rush Cavalerie : 1 gisement de chevaux non exploité"


def test_science_focus_real_kongo_picks_most_populated_cities(game_db: GameDb) -> None:
    actions = plan_actions(state_from(real_t050()), game_db, "science_campus")
    # Éducation est déjà en cours : pas d'action de recherche. Les deux villes sans campus les plus peuplées.
    assert titles(actions) == ["Construire Campus à Kwango", "Construire Campus à Mbanza Mpangu"]


def test_cavalry_focus_real_kongo(game_db: GameDb) -> None:
    actions = focus_actions(state_from(real_t050()), game_db, "cavalry_rush")
    assert "Rechercher Étriers" in titles(actions)
    assert "Produire 4 × Cavalier" in titles(actions)


def test_building_follows_district(game_db: GameDb, mvp1_state_dict: dict) -> None:
    mvp1_state_dict["techs"]["researched"] += ["TECH_WRITING"]
    mvp1_state_dict["cities"][1]["districts"].append("DISTRICT_CAMPUS")
    actions = focus_actions(state_from(mvp1_state_dict), game_db, "science_campus")
    assert "Construire Bibliothèque à Aigai" in titles(actions)
    assert "Construire Campus à Pella" in titles(actions)
    assert not any("Aigai" in t and "Campus" in t for t in titles(actions))


def test_city_already_producing_is_skipped(game_db: GameDb, mvp1_state_dict: dict) -> None:
    mvp1_state_dict["techs"]["researched"] += ["TECH_WRITING"]
    mvp1_state_dict["cities"][1]["current_production"] = "DISTRICT_CAMPUS"
    actions = plan_actions(state_from(mvp1_state_dict), game_db, "science_campus")
    assert titles(a for a in actions if a.category == "production") == ["Construire Campus à Pella"]
    # Écriture acquise : la recherche vise Éducation, dont le chemin passe par Tir à l'arc.
    research = next(a for a in actions if a.category == "research")
    assert research.reason == "Focus Scientifique : en route vers Éducation (Université)"


def with_sites(data: dict, district: str, adjacency_by_city: dict[int, float]) -> dict:
    """Ajoute des emplacements exportés (comme le ferait le mod) : index de ville -> adjacence."""
    for index, city in enumerate(data["cities"]):
        city["district_sites"] = (
            {district: {"adjacency": adjacency_by_city[index], "hex_x": 0, "hex_y": 0}}
            if index in adjacency_by_city else {}
        )
    return data


def test_district_cities_ranked_by_game_adjacency(game_db: GameDb) -> None:
    # Bukavu (2 hab.) a le meilleur emplacement ; Mbanza Mpangu n'a aucun emplacement valide.
    data = with_sites(real_t050(), "DISTRICT_CAMPUS", {3: 1, 5: 4})
    actions = [a for a in focus_actions(state_from(data), game_db, "science_campus") if a.category == "production"]
    assert titles(actions) == ["Construire Campus à Bukavu", "Construire Campus à Kwango"]
    assert actions[0].reason == "Focus Scientifique : meilleur emplacement, adjacence +4"
    assert actions[0].priority > actions[1].priority


def test_district_without_adjacency_bonus(game_db: GameDb) -> None:
    # Un emplacement à +2 et un sans bonus : le second est explicité comme tel.
    data = with_sites(real_t050(), "DISTRICT_CAMPUS", {3: 0, 5: 2})
    actions = [a for a in focus_actions(state_from(data), game_db, "science_campus") if a.category == "production"]
    assert [a.reason for a in actions] == [
        "Focus Scientifique : meilleur emplacement, adjacence +2",
        "Focus Scientifique : emplacement sans bonus d'adjacence",
    ]


def test_districts_without_any_adjacency_ranked_by_population(game_db: GameDb) -> None:
    # Campement : jamais de bonus d'adjacence ; seules les villes avec un emplacement valide comptent.
    data = with_sites(real_t050(), "DISTRICT_ENCAMPMENT", {3: 0, 4: 0, 5: 0})
    actions = [a for a in focus_actions(state_from(data), game_db, "medieval_army") if a.category == "production"]
    assert titles(actions)[:2] == ["Construire Campement à Kwango", "Construire Campement à Mbanza Mpangu"]
    assert actions[0].reason == "Armée médiévale : ville sans Campement (3 habitants)"


def test_culture_focus_adopts_civics(game_db: GameDb) -> None:
    actions = focus_actions(state_from(real_t050()), game_db, "culture_victory")
    civic = next(a for a in actions if a.category == "civic")
    assert civic.title.startswith("Adopter ")
    assert civic.reason.startswith("Victoire culturelle : débloque ")
    assert civic.target_type == "CIVIC_DRAMA_POETRY"


def test_barracks_or_stable_alternatives(game_db: GameDb) -> None:
    data = real_t050()
    data["cities"][0]["districts"].append("DISTRICT_ENCAMPMENT")
    data["cities"][0]["buildings"].append("BUILDING_STABLE")
    data["techs"]["researched"] += ["TECH_MILITARY_ENGINEERING"]
    actions = focus_actions(state_from(data), game_db, "medieval_army")
    city_name = data["cities"][0]["name"]
    # L'écurie remplace la caserne (exclusives) : l'étape suivante est l'armurerie.
    assert f"Construire Armurerie à {city_name}" in titles(actions)
    assert f"Construire Caserne à {city_name}" not in titles(actions)


def test_religious_units_need_a_religion(game_db: GameDb) -> None:
    data = real_t050()
    assert not any(a.id.endswith(":units") for a in focus_actions(state_from(data), game_db, "religious_victory"))
    data["player"]["religion"] = "RELIGION_ORTHODOXY"
    data["cities"][0]["buildings"].append("BUILDING_SHRINE")
    units = [a for a in focus_actions(state_from(data), game_db, "religious_victory") if a.id.endswith(":units")]
    assert len(units) == 1 and units[0].reason.endswith("0/3 unités religieuses")


def test_unknown_strategy_gives_nothing(game_db: GameDb, mvp1_state_dict: dict) -> None:
    assert focus_actions(state_from(mvp1_state_dict), game_db, "nope") == []


# --- Intégration dans run_rules --------------------------------------------------

def test_followed_strategy_reorders_actions(game_db: GameDb) -> None:
    state = state_from(real_t050())
    plain = {a.id: a for a in run_rules(state, game_db)}
    focused = run_rules(state, game_db, followed_strategy="science_campus")

    assert focused[0].strategy == "science_campus"
    for action in focused:
        if action.strategy is None and action.id in plain:
            expected = plain[action.id].priority
            if expected < URGENT_PRIORITY:
                expected -= 15
            assert action.priority == expected


def test_urgent_actions_stay_on_top(game_db: GameDb, mvp1_state_dict: dict) -> None:
    actions = run_rules(state_from(mvp1_state_dict), game_db, followed_strategy="science_campus")
    assert [a.id for a in actions[:2]] == ["idle_research:civic", "idle_city:65536"]


def test_focus_actions_match_contract(game_db: GameDb) -> None:
    actions = run_rules(state_from(real_t050()), game_db, followed_strategy="cavalry_rush")
    message = {
        "type": "recommendations", "schema_version": 1, "turn": 1, "generated_at": "x",
        "followed_strategy": "cavalry_rush", "snapshot": {}, "milestones": [], "strategies": [],
        "actions": [a.to_message() for a in actions],
    }
    assert contracts.first_error("recommendations", message) is None
    assert any(a["strategy"] == "cavalry_rush" for a in message["actions"])


# --- Persistance -------------------------------------------------------------------

def test_followed_strategies_persist_per_game(tmp_path: Path) -> None:
    prefs = FollowedStrategies(tmp_path)
    prefs.set("game-a", "science_campus")
    prefs.set("game-b", "cavalry_rush")
    prefs.set("game-b", None)

    reloaded = FollowedStrategies(tmp_path)
    assert reloaded.get("game-a") == "science_campus"
    assert reloaded.get("game-b") is None
    assert reloaded.get(None) is None


# --- Service et WebSocket ------------------------------------------------------------

class CaptureBroadcaster:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.on_client_message = None

    def publish(self, message: dict) -> None:
        assert contracts.first_error("recommendations", message) is None, message
        self.messages.append(message)


def make_service(tmp_path: Path, game_db_path: Path) -> tuple[EngineService, CaptureBroadcaster]:
    config = EngineConfig(
        lua_log=tmp_path / "Lua.log", gameplay_db=game_db_path, localization_db=game_db_path,
        language="fr_FR", game_dir=None, data_dir=tmp_path / "data", ws_host="127.0.0.1", ws_port=0, poll_interval_s=0.1,
    )
    broadcaster = CaptureBroadcaster()
    return EngineService(config, broadcaster), broadcaster


def test_service_recomputes_on_follow(tmp_path: Path, game_db_path: Path) -> None:
    service, broadcaster = make_service(tmp_path, game_db_path)
    data = real_t050()
    data["meta"]["trigger"] = "turn_end"  # même sur turn_end, un changement de stratégie recalcule
    service.handle_payload(json.dumps(data).encode())
    assert broadcaster.messages[-1]["followed_strategy"] is None

    broadcaster.on_client_message({"type": "follow_strategy", "schema_version": 1, "strategy_id": "science_campus"})
    message = broadcaster.messages[-1]
    assert message["followed_strategy"] == "science_campus"
    assert message["actions"][0]["strategy"] == "science_campus"

    # Le choix survit à un redémarrage du service.
    restarted, broadcaster2 = make_service(tmp_path, game_db_path)
    data["meta"]["trigger"] = "turn_begin"
    restarted.handle_payload(json.dumps(data).encode())
    assert broadcaster2.messages[-1]["followed_strategy"] == "science_campus"


def test_service_ignores_unknown_strategy(tmp_path: Path, game_db_path: Path) -> None:
    service, broadcaster = make_service(tmp_path, game_db_path)
    service.handle_payload((FIXTURES / "game_state_real_t050.json").read_bytes())
    count = len(broadcaster.messages)
    service.handle_client_message({"type": "follow_strategy", "schema_version": 1, "strategy_id": "nope"})
    assert len(broadcaster.messages) == count


def test_websocket_delivers_client_messages() -> None:
    received: list[dict] = []

    async def scenario() -> None:
        broadcaster = Broadcaster("127.0.0.1", 0)
        broadcaster.on_client_message = received.append
        await broadcaster.start()
        try:
            async with connect(f"ws://127.0.0.1:{broadcaster.port}") as ws:
                await ws.send("pas du json")
                await ws.send(json.dumps({"type": "follow_strategy", "schema_version": 1, "strategy_id": 3}))
                await ws.send(json.dumps({"type": "follow_strategy", "schema_version": 1, "strategy_id": "cavalry_rush"}))
                for _ in range(50):
                    if received:
                        break
                    await asyncio.sleep(0.02)
        finally:
            await broadcaster.stop()

    asyncio.run(scenario())
    assert received == [{"type": "follow_strategy", "schema_version": 1, "strategy_id": "cavalry_rush"}]


# --- Actions communes : expansion, bâtisseurs, quartiers hors quota ---------------------

def test_settler_during_expansion(game_db: GameDb, mvp1_state_dict: dict) -> None:
    actions = {a.id: a for a in focus_actions(state_from(mvp1_state_dict), game_db, "science_campus")}
    settler = actions["focus:science_campus:settlers"]
    assert (settler.title, settler.priority) == ("Produire Colon à Pella", 75)
    assert settler.reason.endswith("2/6 villes : s'étendre tôt multiplie la production")


def test_no_settler_when_one_is_on_its_way_or_expansion_is_over(game_db: GameDb, mvp1_state_dict: dict) -> None:
    on_its_way = json.loads(json.dumps(mvp1_state_dict))
    on_its_way["units"].append({"unit_id": 99, "type": "UNIT_SETTLER", "hex_x": 1, "hex_y": 1})
    late = json.loads(json.dumps(mvp1_state_dict))
    late["game"]["era"] = "ERA_RENAISSANCE"
    for data in (on_its_way, late):
        assert not any(a.id.endswith(":settlers") for a in focus_actions(state_from(data), game_db, "science_campus"))


def test_cavalry_rush_aims_for_fewer_cities(game_db: GameDb, mvp1_state_dict: dict) -> None:
    (settler,) = [a for a in focus_actions(state_from(mvp1_state_dict), game_db, "cavalry_rush") if "Colon" in a.title]
    assert "2/4 villes" in settler.reason


def test_builder_when_resources_wait(game_db: GameDb, mvp1_state_dict: dict) -> None:
    state = state_from(mvp1_state_dict)
    assert not any(a.id.endswith(":builders") for a in focus_actions(state, game_db, "science_campus"))
    mvp1_state_dict["units"] = [u for u in mvp1_state_dict["units"] if u["type"] != "UNIT_BUILDER"]
    (builder,) = [a for a in focus_actions(state_from(mvp1_state_dict), game_db, "science_campus")
                  if a.id.endswith(":builders")]
    # Pâturage (chevaux) et carrière (pierre) débloqués ; le coton attend l'Irrigation.
    assert builder.title == "Produire Bâtisseur à Pella"
    assert builder.reason.endswith("2 ressources à aménager pour 0 bâtisseur")


def test_aqueduct_when_housing_is_short(game_db: GameDb, mvp1_state_dict: dict) -> None:
    mvp1_state_dict["techs"]["researched"] += ["TECH_ENGINEERING"]
    actions = {a.id: a for a in focus_actions(state_from(mvp1_state_dict), game_db, "science_campus")}
    aqueduct = actions["focus:science_campus:support:65536"]  # Pella
    assert (aqueduct.title, aqueduct.priority) == ("Construire Aqueduc à Pella", 74)
    assert "logement saturé (3/3.5)" in aqueduct.reason and "hors quota" in aqueduct.reason


def test_kongo_gets_mbanza_without_aqueduct(game_db: GameDb, mvp1_state_dict: dict) -> None:
    mvp1_state_dict["player"].update(civilization="CIVILIZATION_KONGO", leader="LEADER_MVEMBA")
    mvp1_state_dict["civics"]["unlocked"] += ["CIVIC_GUILDS"]
    actions = {a.id: a for a in focus_actions(state_from(mvp1_state_dict), game_db, "science_campus")}
    mbanza = actions["focus:science_campus:support:65536"]  # Pella
    assert mbanza.title == "Construire Mbanza à Pella" and "+5 logements" in mbanza.reason


def test_dam_needs_a_known_site(game_db: GameDb, mvp1_state_dict: dict) -> None:
    mvp1_state_dict["techs"]["researched"] += ["TECH_BUTTRESS"]
    assert not any(":support:" in a.id for a in focus_actions(state_from(mvp1_state_dict), game_db, "science_campus"))
    mvp1_state_dict["cities"][1]["district_sites"] = {"DISTRICT_DAM": {"adjacency": 0, "hex_x": 1, "hex_y": 1}}
    (dam,) = [a for a in focus_actions(state_from(mvp1_state_dict), game_db, "science_campus") if ":support:" in a.id]
    assert dam.title == "Construire Barrage à Aigai" and "crues" in dam.reason
