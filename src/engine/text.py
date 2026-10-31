"""Petits utilitaires de rédaction en français pour les textes affichés."""

from __future__ import annotations


def de(name: str) -> str:
    """« de Roue », « d'Irrigation » (élision devant voyelle ou h muet)."""
    return f"d'{name}" if name[:1].lower() in "aâàeéèêiîoôuûh" else f"de {name}"


def plural(count: float, singular: str, plural_form: str | None = None) -> str:
    """« 1 cheval », « 3 chevaux », « 2 villes »."""
    word = singular if abs(count) <= 1 else (plural_form or singular + "s")
    return f"{count:g} {word}"


def signed(value: float) -> str:
    """« +5 », « +46.3 », « -2 »."""
    text = f"{value:+.1f}"
    return text[:-2] if text.endswith(".0") else text
