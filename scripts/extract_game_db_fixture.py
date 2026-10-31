"""Extrait de la vraie base du jeu la fixture de test tests/fixtures/game_db.sql.

Ne garde que les tables et colonnes lues par engine.game_db, plus les noms localisés
(fr_FR et en_US) des types. À relancer quand le schéma utilisé change :

    python scripts/extract_game_db_fixture.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engine.config import civ6_app_data_dir, civ6_install_dir  # noqa: E402
from engine.game_db import NAMED_TABLES, TABLES, load_names  # noqa: E402
from engine.game_text import load_xml_names  # noqa: E402

OUTPUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "game_db.sql"


def main() -> None:
    cache = civ6_app_data_dir() / "Cache"
    source = sqlite3.connect(f"{(cache / 'DebugGameplay.sqlite').as_uri()}?mode=ro", uri=True)
    localization = sqlite3.connect(f"{(cache / 'DebugLocalization.sqlite').as_uri()}?mode=ro", uri=True)
    target = sqlite3.connect(":memory:")

    for table, columns in TABLES.items():
        target.execute(f"CREATE TABLE {table} ({', '.join(columns)})")
        rows = source.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
        target.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(columns))})", rows)

    tags = {tag for table in NAMED_TABLES for (tag,) in source.execute(f"SELECT Name FROM {table}")}
    target.execute("CREATE TABLE LocalizedText (Language, Tag, Text)")
    game_dir = civ6_install_dir()
    for language in ("en_US", "fr_FR"):
        # Sans repli : chaque langue ne contient que ses propres textes, complétés par les
        # traductions des extensions (fichiers XML de l'installation), comme le fait GameDb.load.
        names = load_names(localization, tags, language, fallback=None)
        if game_dir is not None:
            names |= load_xml_names(game_dir, tags - names.keys(), language)
        target.executemany("INSERT INTO LocalizedText VALUES (?, ?, ?)", [(language, k, v) for k, v in names.items()])

    OUTPUT.write_text("\n".join(target.iterdump()) + "\n", encoding="utf-8")
    print(f"{OUTPUT} ({OUTPUT.stat().st_size // 1024} Ko)")


if __name__ == "__main__":
    main()
