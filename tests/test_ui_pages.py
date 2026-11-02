"""Pages de l'overlay (spec 03 §4), testées hors écran sur un vrai message du moteur."""

from __future__ import annotations

import copy
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from conftest import FIXTURES, state_from
from engine.recommendations import build_recommendations
from engine.rules import run_rules
from engine.strategies import score_strategies
from ui.overlay_window import Mode, OverlayWindow
from ui.settings import UiSettings


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch) -> OverlayWindow:
    monkeypatch.setenv("APPDATA", str(tmp_path))  # ne pas toucher aux vrais réglages
    return OverlayWindow(UiSettings())


def message(game_db, followed: str | None, game_id: str = "g1") -> dict:
    state = state_from(json.loads((FIXTURES / "game_state_real_t050.json").read_text(encoding="utf-8")))
    return build_recommendations(
        state, game_id,
        actions=[a.to_message() for a in run_rules(state, game_db, followed_strategy=followed)],
        strategies=score_strategies(state, game_db),
        followed_strategy=followed,
    )


def texts(widget) -> list[str]:
    return [label.text() for label in widget.findChildren(QLabel) if label.isVisibleTo(widget)]


def test_new_game_without_strategy_opens_strategy_choice(window, game_db) -> None:
    window.on_recommendations(message(game_db, None))
    assert window.current_page() == "strategies"
    assert any(t.startswith("Choisissez une stratégie") for t in texts(window._strategies_page))


def test_choosing_a_strategy_switches_to_actions(window, game_db) -> None:
    window.on_recommendations(message(game_db, None))
    window.on_recommendations(message(game_db, "medieval_army"))
    assert window.current_page() == "actions"
    page_texts = texts(window._actions_page)
    assert "★ Armée médiévale · 80 %" in page_texts
    assert "Plan : Armée médiévale" in page_texts


def test_page_kept_on_new_turn_with_same_strategy(window, game_db) -> None:
    window.on_recommendations(message(game_db, "medieval_army"))
    window.show_page("settle")
    window.on_recommendations(message(game_db, "medieval_army"))
    assert window.current_page() == "settle"


def test_new_game_resets_page(window, game_db) -> None:
    window.on_recommendations(message(game_db, "medieval_army", game_id="g1"))
    window.show_page("settle")
    window.on_recommendations(message(game_db, None, game_id="g2"))
    assert window.current_page() == "strategies"


def test_actions_split_into_sections(window, game_db) -> None:
    msg = message(game_db, "medieval_army")
    window.on_recommendations(msg)
    plan = [a for a in msg["actions"] if a.get("strategy") == "medieval_army"]
    others = [a for a in msg["actions"] if not a.get("strategy")]
    assert plan and others
    assert window._actions_page._others.isVisibleTo(window._actions_page)
    assert f"▸ Autres opportunités ({len(others)})" in [
        b.text() for b in window._actions_page.findChildren(QPushButton)
    ]


def test_follow_button_emits_choice(window, game_db) -> None:
    received = []
    window.follow_requested.connect(received.append)
    window.on_recommendations(message(game_db, None))
    buttons = [b for b in window._strategies_page.findChildren(QPushButton) if b.text() == "Suivre"]
    buttons[0].click()  # première carte = meilleur score = Armée médiévale
    assert received == ["medieval_army"]


def test_strategy_choice_switches_to_interactive_and_back(window, game_db) -> None:
    assert window.mode() is Mode.CLICK_THROUGH
    window.on_recommendations(message(game_db, None))
    assert window.mode() is Mode.INTERACTIVE  # « Suivre » doit être cliquable
    window.on_recommendations(message(game_db, "medieval_army"))
    assert window.mode() is Mode.CLICK_THROUGH


def test_manual_mode_change_is_respected(window, game_db) -> None:
    window.on_recommendations(message(game_db, None))
    window.toggle_mode()  # le joueur repasse en click-through…
    window.toggle_mode()  # …puis en interactif, volontairement
    window.on_recommendations(message(game_db, "medieval_army"))
    assert window.mode() is Mode.INTERACTIVE


def test_already_interactive_player_stays_interactive(window, game_db) -> None:
    window.on_recommendations(message(game_db, "medieval_army"))
    window.toggle_mode()  # interactif, par le joueur
    window.on_recommendations(message(game_db, None))  # « Ne plus suivre »
    window.on_recommendations(message(game_db, "science_campus"))
    assert window.mode() is Mode.INTERACTIVE


def test_next_page_cycles(window) -> None:
    window.show_page("actions")
    visited = []
    for _ in range(4):
        window.next_page()
        visited.append(window.current_page())
    assert visited == ["strategies", "cities", "settle", "actions"]


# --- Page Villes ------------------------------------------------------------------

def cities_message(game_db, mvp1_state_dict) -> dict:
    from city_map import hex_patch, ring1
    from engine.city_layout import CityPlotsCache, city_layouts

    data = copy.deepcopy(mvp1_state_dict)
    center = (14, 20)
    owned = ring1(center)
    data["cities"][0]["plots"] = hex_patch(center, owned, {c: {"sites": {"DISTRICT_CAMPUS": 2}} for c in owned})
    data["cities"][0]["district_slots"] = {"used": 0, "allowed": 1}
    data["cities"][1]["plots"] = hex_patch((19, 22), ring1((19, 22)))
    data["techs"]["researched"].append("TECH_WRITING")
    state = state_from(data)
    msg = message(game_db, None)
    msg["cities"] = city_layouts(state, game_db, CityPlotsCache().update("g", state), None)
    return msg


def test_cities_page_lists_cities_and_layout(window, game_db, mvp1_state_dict) -> None:
    window.on_recommendations(cities_message(game_db, mvp1_state_dict))
    page = window._cities_page
    assert [page._combo.itemText(i) for i in range(page._combo.count())] == ["Pella (3)", "Aigai (1)"]
    page_texts = texts(page)
    assert "Quartiers : 0/1 · 1 emplacement libre" in page_texts
    assert "Campus" in page_texts and "maintenant" in page_texts


def test_next_city_hotkey(window, game_db, mvp1_state_dict) -> None:
    window.on_recommendations(cities_message(game_db, mvp1_state_dict))
    window.show_page("actions")
    window.next_city()  # ouvre d'abord la page
    assert window.current_page() == "cities"
    assert window._cities_page.selected_city()["name"] == "Pella"
    window.next_city()
    assert window._cities_page.selected_city()["name"] == "Aigai"
    assert "Aucun quartier à placer pour l'instant" in texts(window._cities_page)


def test_selected_city_kept_across_updates(window, game_db, mvp1_state_dict) -> None:
    msg = cities_message(game_db, mvp1_state_dict)
    window.on_recommendations(msg)
    window._cities_page.next_city()
    window.on_recommendations(msg)
    assert window._cities_page.selected_city()["name"] == "Aigai"


def test_cities_page_without_maps(window, game_db) -> None:
    window.on_recommendations(message(game_db, None))
    assert "Carte des villes disponible au début du prochain tour" in texts(window._cities_page)


def test_city_border_follows_owned_tiles() -> None:
    from ui.widgets.hex_map import HexMap

    ring1 = [(1, 0), (0.5, 1), (-0.5, 1), (-1, 0), (-0.5, -1), (0.5, -1)]
    tiles = [{"x": 0, "y": 0, "owned": True}] + [{"x": x, "y": y, "owned": True} for x, y in ring1]
    tiles += [{"x": 2, "y": 0, "owned": False}]
    edges = HexMap._border_edges(tiles)
    # Centre entouré : aucun côté ; anneau 1 : 3 côtés extérieurs par tuile.
    assert len(edges) == 18
    assert HexMap._border_edges([{"x": 0, "y": 0, "owned": True}]).__len__() == 6


def test_locked_districts_hidden_unless_checked(window, game_db, mvp1_state_dict) -> None:
    msg = cities_message(game_db, mvp1_state_dict)
    locked = dict(msg["cities"][0]["layout"][0], kind="DISTRICT_THEATER", label="Place du théâtre",
                  status="later", unlocked=False, requires="Théâtre et poésie")
    msg["cities"][0]["layout"].append(locked)
    window.on_recommendations(msg)
    page = window._cities_page
    assert "Place du théâtre" not in texts(page)
    page._show_locked.setChecked(True)
    assert "Place du théâtre" in texts(page) and "🔒 Théâtre et poésie" in texts(page)
    assert window._settings.show_locked_districts is True


def test_built_districts_legend_lists_each_kind_once() -> None:
    from ui.pages.cities_page import CitiesPage

    city = {"tiles": [
        {"district": "DISTRICT_NEIGHBORHOOD", "district_label": "Quartier résidentiel", "owned": False,
         "other_city": "Aigai"},
        {"district": "DISTRICT_CITY_CENTER", "district_label": "Centre-ville", "owned": True},
        {"district": "DISTRICT_CAMPUS", "district_label": "Campus", "owned": True},
        {"district": "DISTRICT_CAMPUS", "district_label": "Campus", "owned": False, "other_city": "Aigai"},
        {"district": "DISTRICT_NEIGHBORHOOD", "district_label": "Mbanza", "owned": True},
        {"district": "DISTRICT_HOLY_SITE", "district_label": "Lieu saint", "owned": False, "foreign": True},
    ]}
    # Une entrée par sorte ; le nom vient de préférence d'un quartier de la ville (Mbanza).
    assert CitiesPage.built_districts(city) == [
        ("DISTRICT_CITY_CENTER", "Centre-ville"), ("DISTRICT_CAMPUS", "Campus"),
        ("DISTRICT_NEIGHBORHOOD", "Mbanza"), ("DISTRICT_HOLY_SITE", "Lieu saint"),
    ]


def test_layout_limit_and_collapsible_legend(window, game_db, mvp1_state_dict) -> None:
    msg = cities_message(game_db, mvp1_state_dict)
    entry = msg["cities"][0]["layout"][0]
    msg["cities"][0]["layout"] = [dict(entry, label=f"Quartier {i}") for i in range(7)]
    window.on_recommendations(msg)
    page = window._cities_page
    assert "Quartier 4" in texts(page) and "Quartier 5" not in texts(page)  # 5 par défaut
    assert "+2 autres quartiers masqués" in texts(page)
    page._limit.setCurrentIndex(page._limit.findData(0))
    assert "Quartier 6" in texts(page) and window._settings.layout_limit == 0
    page._legend._toggle()
    assert window._settings.collapsed["city_legend"] is True
    assert not page._legend.content.isVisibleTo(page)
