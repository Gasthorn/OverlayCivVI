"""Accès aux JSON Schemas de specs/schemas/ (partagé entre le moteur et l'UI)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "specs" / "schemas"


@lru_cache(maxsize=None)
def validator(name: str) -> Draft202012Validator:
    """Retourne le validateur du schéma `specs/schemas/<name>.schema.json`."""
    schema = json.loads((SCHEMAS_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def first_error(name: str, instance: object) -> str | None:
    """Message de la première erreur de validation, ou None si l'instance est valide."""
    error = next(iter(validator(name).iter_errors(instance)), None)
    if error is None:
        return None
    path = "/".join(str(p) for p in error.absolute_path) or "<racine>"
    return f"{path} : {error.message}"
