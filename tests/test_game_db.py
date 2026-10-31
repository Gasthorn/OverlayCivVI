from __future__ import annotations

from pathlib import Path

from engine.game_db import GameDb, GameDbProvider


def test_names_are_localized_and_singular(game_db: GameDb) -> None:
    assert game_db.name("TECH_HORSEBACK_RIDING") == "Équitation"
    assert game_db.name("UNIT_SCOUT") == "Éclaireur"  # « Éclaireur|Éclaireurs »
    assert game_db.name("RESOURCE_HORSES") == "Chevaux"


def test_unknown_type_gets_readable_fallback(game_db: GameDb) -> None:
    assert game_db.name("UNIT_MY_MOD_THING") == "My mod thing"
    assert game_db.name(None) == "—"


def test_available_techs_follow_prereqs(game_db: GameDb) -> None:
    available = game_db.available_techs({"TECH_POTTERY", "TECH_ANIMAL_HUSBANDRY", "TECH_MINING"})
    assert {"TECH_ARCHERY", "TECH_IRRIGATION", "TECH_WRITING", "TECH_MASONRY", "TECH_BRONZE_WORKING"} <= set(available)
    assert "TECH_HORSEBACK_RIDING" not in available  # Tir à l'arc requis
    assert "TECH_POTTERY" not in available


def test_future_era_techs_without_prereqs_are_never_available(game_db: GameDb) -> None:
    available = game_db.available_techs(set())
    assert "TECH_SEASTEADS" not in available
    assert set(available) >= {"TECH_POTTERY", "TECH_ANIMAL_HUSBANDRY", "TECH_MINING"}


def test_resolve_unique_unit_for_macedon(game_db: GameDb) -> None:
    traits = game_db.player_traits("CIVILIZATION_MACEDON", "LEADER_JFD_OLYMPIAS")
    assert game_db.resolve_for_player("UNIT_SWORDSMAN", traits) == "UNIT_MACEDONIAN_HYPASPIST"
    assert game_db.resolve_for_player("UNIT_SWORDSMAN", set()) == "UNIT_SWORDSMAN"
    assert "UNIT_MACEDONIAN_HYPASPIST" in game_db.variants("UNIT_SWORDSMAN")


def test_unique_unit_not_buildable_by_other_civs(game_db: GameDb) -> None:
    assert game_db.resolve_for_player("UNIT_MACEDONIAN_HYPASPIST", set()) is None


def test_boosts_read_from_database(game_db: GameDb) -> None:
    boost = game_db.boosts["TECH_HORSEBACK_RIDING"]
    assert boost.boost_class == "BOOST_TRIGGER_HAVE_X_IMPROVEMENTS"
    assert boost.improvement == "IMPROVEMENT_PASTURE"
    assert boost.percent == 40  # Gathering Storm


def test_speed_multiplier(game_db: GameDb) -> None:
    assert game_db.speed_multiplier("GAMESPEED_EPIC") == 1.5
    assert game_db.speed_multiplier(None) == 1.0


def test_provider_reports_missing_database(tmp_path: Path) -> None:
    provider = GameDbProvider(tmp_path / "absent.sqlite", None, "fr_FR")
    assert provider.get() is None
    assert "introuvable" in (provider.error or "")


def test_xml_translations_fill_missing_names(tmp_path) -> None:
    from engine.game_text import load_xml_names

    text_dir = tmp_path / "DLC" / "Expansion2" / "Text"
    text_dir.mkdir(parents=True)
    (text_dir / "Expansion2_Translations_Text.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<GameData><LocalizedText>
  <Replace Tag="LOC_DISTRICT_DAM_NAME" Language="de_DE"><Text>Staudamm</Text></Replace>
  <Replace Tag="LOC_DISTRICT_DAM_NAME" Language="fr_FR"><Text>Barrage|Barrages</Text></Replace>
  <Row Tag="LOC_DISTRICT_PRESERVE_NAME" Language="fr_FR"><Text>Réserve</Text></Row>
</LocalizedText></GameData>""",
        encoding="utf-8",
    )
    scenario = tmp_path / "DLC" / "PiratesScenario" / "Text"
    scenario.mkdir(parents=True)
    (scenario / "Pirates_Translations_Text.xml").write_text(
        '<GameData><LocalizedText><Replace Tag="LOC_DISTRICT_DAM_NAME" Language="fr_FR">'
        "<Text>Faux</Text></Replace></LocalizedText></GameData>",
        encoding="utf-8",
    )
    names = load_xml_names(tmp_path, {"LOC_DISTRICT_DAM_NAME", "LOC_DISTRICT_PRESERVE_NAME", "LOC_X"}, "fr_FR")
    assert names == {"LOC_DISTRICT_DAM_NAME": "Barrage|Barrages", "LOC_DISTRICT_PRESERVE_NAME": "Réserve"}
