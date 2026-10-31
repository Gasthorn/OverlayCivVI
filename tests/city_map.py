"""Cartes de ville synthétiques au format `cities[].plots` (spec 01 §5), pour les tests."""

from __future__ import annotations

from typing import Any


def neighbor_coords(x: int, y: int, odd_shifted: bool = True) -> list[tuple[int, int]]:
    """Voisins sur une grille à rangées décalées (rangées impaires décalées à droite par défaut)."""
    shifted = (y % 2 == 1) == odd_shifted
    dx = (0, 1) if shifted else (-1, 0)
    return [
        (x - 1, y), (x + 1, y),
        (x + dx[0], y - 1), (x + dx[1], y - 1),
        (x + dx[0], y + 1), (x + dx[1], y + 1),
    ]


def hex_patch(
    center: tuple[int, int],
    owned: set[tuple[int, int]],
    tiles: dict[tuple[int, int], dict[str, Any]] | None = None,
    odd_shifted: bool = True,
) -> list[dict[str, Any]]:
    """Tuiles possédées + anneau de voisins, avec indices et voisins cohérents.

    `tiles` complète une tuile (terrain, district, sites…) ; par défaut : prairie vide.
    """
    tiles = tiles or {}
    coords = set(owned)
    for x, y in owned:
        coords.update(neighbor_coords(x, y, odd_shifted))
    coords.add(center)
    index = {c: i for i, c in enumerate(sorted(coords, key=lambda c: (c[1], c[0])))}

    plots = []
    for (x, y), i in sorted(index.items(), key=lambda kv: kv[1]):
        plot = {
            "index": i, "hex_x": x, "hex_y": y, "terrain": "TERRAIN_GRASS",
            "owned": (x, y) in owned or (x, y) == center,
            "neighbors": [index.get(c, -1) for c in neighbor_coords(x, y, odd_shifted)],
        }
        if (x, y) == center:
            plot["district"] = "DISTRICT_CITY_CENTER"
        if plot["owned"]:
            plot["sites"] = {}
        plot.update(tiles.get((x, y), {}))
        plots.append(plot)
    return plots


def ring1(center: tuple[int, int], odd_shifted: bool = True) -> set[tuple[int, int]]:
    return set(neighbor_coords(*center, odd_shifted))
