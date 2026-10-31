"""Textes localisés absents de DebugLocalization.sqlite, lus dans les fichiers XML du jeu (spec 02 §4).

Le cache de localisation ne contient pas toujours les traductions des extensions (constaté le
2026-10-29 : « Barrage », « Place du gouvernement »… n'y sont qu'en anglais, voire absents). Les
fichiers `DLC/<extension>/Text/*Translations*.xml` de l'installation les contiennent, sous la forme
`<Replace Tag="LOC_…" Language="fr_FR"><Text>Barrage|Barrages</Text></Replace>` (ou `<Row …>`).
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from pathlib import Path

log = logging.getLogger(__name__)

# Scénarios et variantes régionales : leurs textes ne valent que dans leur propre contexte.
_SKIPPED = ("Scenario", "_China")


def translation_files(game_dir: Path) -> list[Path]:
    files = sorted((game_dir / "DLC").glob("*/Text/*.xml"))
    return [f for f in files if not any(s in str(f.relative_to(game_dir)) for s in _SKIPPED)]


def load_xml_names(game_dir: Path, tags: Iterable[str], language: str) -> dict[str, str]:
    """Textes des `tags` dans la langue demandée, trouvés dans les fichiers XML des DLC."""
    wanted = set(tags)
    found: dict[str, str] = {}
    if not wanted:
        return found
    needles = {tag.encode() for tag in wanted}
    for path in translation_files(game_dir):
        try:
            data = path.read_bytes()
        except OSError as exc:
            log.warning("Traductions illisibles (%s) : %s", path, exc)
            continue
        if not any(needle in data for needle in needles):
            continue  # filtre rapide : la plupart des fichiers ne contiennent aucun tag cherché
        try:
            root = ET.fromstring(data)
        except ET.ParseError as exc:
            log.warning("Traductions mal formées (%s) : %s", path, exc)
            continue
        for element in root.iter():
            tag = element.get("Tag")
            if tag in wanted and element.get("Language", "en_US") == language:
                text = element.get("Text") or element.findtext("Text")
                if text:
                    found[tag] = text
    return found
