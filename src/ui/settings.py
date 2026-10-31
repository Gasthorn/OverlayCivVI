"""Persistance des réglages de la fenêtre dans %APPDATA%\\CivVISmartOverlay\\ui.json (spec 03 §3.2)."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)


def settings_path() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home()))
    return base / "CivVISmartOverlay" / "ui.json"


@dataclass
class UiSettings:
    x: int = 40
    y: int = 40
    width: int = 520
    height: int = 96
    opacity: float = 0.85
    collapsed: dict[str, bool] = field(default_factory=dict)  # état replié, par panel
    show_locked_districts: bool = False  # page Villes : quartiers pas encore débloqués
    layout_limit: int = 5  # page Villes : quartiers conseillés affichés (0 = tous)

    @classmethod
    def load(cls, path: Path | None = None) -> UiSettings:
        path = path or settings_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Réglages illisibles (%s), valeurs par défaut utilisées", exc)
            return cls()
        known = {f.name for f in fields(cls)}
        try:
            return cls(**{k: v for k, v in data.items() if k in known})
        except TypeError:
            return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or settings_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except OSError as exc:
            log.warning("Impossible d'enregistrer les réglages : %s", exc)
