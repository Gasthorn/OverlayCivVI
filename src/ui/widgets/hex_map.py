"""Mini-carte hexagonale d'une ville (spec 03 §4.4) : tuiles, quartiers existants et prévus.

Le moteur fournit les positions de dessin (`tiles[].x/y`, en unités d'hexagone, rangées décalées
déjà appliquées) : ce widget ne fait que dessiner. Le nord est en haut (y croissant vers le haut).
"""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

SQRT3 = math.sqrt(3)

TERRAIN_COLORS = {
    "GRASS": "#4c7a3c", "PLAINS": "#8c8a42", "DESERT": "#c4ae6a", "TUNDRA": "#6f8476",
    "SNOW": "#d6dde4", "COAST": "#3b78a8", "OCEAN": "#264f78",
}
MOUNTAIN_COLOR = "#6b6b70"
RESOURCE_COLORS = {
    "bonus": QColor("#f0c94a"),
    "luxury": QColor("#c77dff"),
    "strategic": QColor("#ff7a45"),
    "artifact": QColor("#c49a6c"),
}
FOREST_FEATURES = {"FEATURE_FOREST", "FEATURE_JUNGLE"}
BORDER_COLOR = "#f5f5f5"
NATURAL_WONDER_ICON = "🏞️"
OTHER_CITY_OPACITY = 0.4

# Hexagones « pointe en haut », en unités de dessin (y vers le haut) : pas vers chaque voisine
# (E, NE, NO, O, SO, SE) et extrémités du côté partagé avec elle.
_V = {30: (0.5, 1 / 3), 90: (0.0, 2 / 3), 150: (-0.5, 1 / 3),
      210: (-0.5, -1 / 3), 270: (0.0, -2 / 3), 330: (0.5, -1 / 3)}
NEIGHBOR_STEPS = [(1, 0), (0.5, 1), (-0.5, 1), (-1, 0), (-0.5, -1), (0.5, -1)]
NEIGHBOR_EDGES = [(_V[330], _V[30]), (_V[30], _V[90]), (_V[90], _V[150]),
                  (_V[150], _V[210]), (_V[210], _V[270]), (_V[270], _V[330])]

# Icône par type générique de quartier (`kind`).
DISTRICT_ICONS = {
    "DISTRICT_CITY_CENTER": "🏛️", "DISTRICT_CAMPUS": "🔬", "DISTRICT_COMMERCIAL_HUB": "💰",
    "DISTRICT_THEATER": "🎭", "DISTRICT_HOLY_SITE": "🛐", "DISTRICT_INDUSTRIAL_ZONE": "⚙️",
    "DISTRICT_HARBOR": "⚓", "DISTRICT_ENCAMPMENT": "⚔️", "DISTRICT_GOVERNMENT": "🏢",
    "DISTRICT_AQUEDUCT": "💧", "DISTRICT_NEIGHBORHOOD": "🏘️", "DISTRICT_ENTERTAINMENT_COMPLEX": "🎪",
    "DISTRICT_WONDER": "🗿", "DISTRICT_AERODROME": "✈️", "DISTRICT_SPACEPORT": "🚀",
    "DISTRICT_DAM": "🌊", "DISTRICT_DIPLOMATIC_QUARTER": "🕊️", "DISTRICT_PRESERVE": "🌳",
    "DISTRICT_WATER_ENTERTAINMENT_COMPLEX": "🏊",
}


def is_own_district(tile: dict[str, Any]) -> bool:
    """Quartier de la ville affichée (et non d'une autre ville du joueur ou d'une autre civilisation)."""
    return bool(tile.get("district")) and bool(tile.get("owned")) and not tile.get("foreign") and not tile.get("other_city")


def terrain_color(terrain: str) -> QColor:
    if terrain.endswith("_MOUNTAIN"):
        return QColor(MOUNTAIN_COLOR)
    base = terrain.removeprefix("TERRAIN_").removesuffix("_HILLS")
    color = QColor(TERRAIN_COLORS.get(base, "#555a60"))
    return color.darker(118) if terrain.endswith("_HILLS") else color


class HexMap(QWidget):
    def __init__(self, height: int = 220) -> None:
        super().__init__()
        self._city: dict[str, Any] | None = None
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(height)

    def set_city(self, city: dict[str, Any] | None) -> None:
        self._city = city
        self.update()

    # --- Géométrie ------------------------------------------------------------------

    def _layout(self) -> tuple[float, float, float]:
        """(taille d'un hexagone, décalage x, décalage y) pour tenir dans le widget."""
        tiles = self._city["tiles"]
        xs = [t["x"] for t in tiles]
        ys = [t["y"] for t in tiles]
        span_x = (max(xs) - min(xs)) * SQRT3 + SQRT3
        span_y = (max(ys) - min(ys)) * 1.5 + 2
        size = min((self.width() - 8) / span_x, (self.height() - 8) / span_y)
        offset_x = (self.width() - (max(xs) - min(xs)) * SQRT3 * size) / 2 - min(xs) * SQRT3 * size
        offset_y = (self.height() - (max(ys) - min(ys)) * 1.5 * size) / 2 + max(ys) * 1.5 * size
        return size, offset_x, offset_y

    @staticmethod
    def _hexagon(center: QPointF, size: float) -> QPolygonF:
        return QPolygonF([
            QPointF(center.x() + size * math.cos(math.radians(90 + 60 * k)),
                    center.y() + size * math.sin(math.radians(90 + 60 * k)))
            for k in range(6)
        ])

    # --- Dessin -----------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if not self._city or not self._city.get("tiles"):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        size, ox, oy = self._layout()

        def center(x: float, y: float) -> QPointF:
            return QPointF(ox + x * SQRT3 * size, oy - y * 1.5 * size)

        positions = {(t["hex_x"], t["hex_y"]): center(t["x"], t["y"]) for t in self._city["tiles"]}
        icon_font = QFont("Segoe UI Emoji", max(7, int(size * 0.55)))
        text_font = QFont("Segoe UI", max(6, int(size * 0.32)), QFont.Bold)

        for tile in self._city["tiles"]:
            c = positions[(tile["hex_x"], tile["hex_y"])]
            color = terrain_color(tile["terrain"])
            if tile.get("foreign"):
                color.setAlpha(70)
            elif not tile["owned"]:
                color.setAlpha(150)  # à acheter : utilisable, mais pas encore à la ville
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(QColor(20, 22, 28), 1))
            painter.drawPolygon(self._hexagon(c, size * 0.97))
            if tile.get("foreign"):
                # Tuile d'une autre civilisation : hachurée, aucun quartier possible.
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(200, 60, 60, 140), Qt.BDiagPattern))
                painter.drawPolygon(self._hexagon(c, size * 0.97))

            if tile.get("feature") in FOREST_FEATURES:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(20, 60, 25, 200))
                painter.drawEllipse(QPointF(c.x() - size * 0.45, c.y() - size * 0.35), size * 0.16, size * 0.16)
            if tile.get("natural_wonder"):
                self._draw_icon(painter, c, size, NATURAL_WONDER_ICON, icon_font, existing=False)
            if tile.get("resource"):
                self._draw_resource(painter, QPointF(c.x() + size * 0.42, c.y() - size * 0.38), size,
                                    tile.get("resource_kind") or "bonus")
            if tile.get("district"):
                if is_own_district(tile):
                    self._draw_icon(painter, c, size, tile["district"], icon_font, existing=True)
                else:
                    # Quartier d'une autre ville (du joueur ou d'une autre civilisation) : estompé.
                    painter.setOpacity(OTHER_CITY_OPACITY)
                    self._draw_icon(painter, c, size, tile["district"], icon_font, existing=False)
                    painter.setOpacity(1.0)

        painter.setPen(QPen(QColor(BORDER_COLOR), max(2.0, size * 0.12), Qt.SolidLine, Qt.RoundCap))
        for start, end in self._border_edges(self._city["tiles"]):
            painter.drawLine(center(*start), center(*end))

        for entry in self._city.get("layout", []):
            c = positions.get((entry["hex_x"], entry["hex_y"]))
            if c is None:
                continue
            later = entry["status"] == "later"
            # Pointillés fins pour un quartier pas encore débloqué, tirets sinon.
            style = Qt.DotLine if entry.get("unlocked") is False else Qt.DashLine
            pen = QPen(QColor("#8a909c") if later else QColor("#f2d36b"), 2, style)
            painter.setPen(pen)
            painter.setBrush(QColor(20, 22, 28, 150))
            painter.drawEllipse(c, size * 0.62, size * 0.62)
            self._draw_icon(painter, c, size, entry["kind"], icon_font, existing=False)
            painter.setFont(text_font)
            painter.setPen(QColor("#8a909c") if later else QColor("#f2d36b"))
            caption = entry.get("caption") or f"{entry['adjacency']:+g}"
            painter.drawText(
                QRectF(c.x() - size, c.y() + size * 0.35, 2 * size, size * 0.6),
                Qt.AlignHCenter | Qt.AlignTop, caption,
            )
        painter.end()

    @staticmethod
    def _border_edges(tiles: list[dict[str, Any]]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        """Frontière de la ville : côtés des tuiles achetées dont la voisine ne l'est pas (ou est
        hors carte). Segments en unités de dessin (x, y), calculés depuis les seules positions."""
        owned = {(round(t["x"] * 2), round(t["y"])) for t in tiles if t["owned"]}
        edges = []
        for tile in tiles:
            if not tile["owned"]:
                continue
            x, y = tile["x"], tile["y"]
            for (dx, dy), (a, b) in zip(NEIGHBOR_STEPS, NEIGHBOR_EDGES):
                if (round((x + dx) * 2), round(y + dy)) not in owned:
                    edges.append(((x + a[0], y + a[1]), (x + b[0], y + b[1])))
        return edges

    @staticmethod
    def _draw_resource(painter: QPainter, at: QPointF, size: float, kind: str) -> None:
        """Ressource bonus : petit point jaune. Luxe, stratégique, site archéologique : losange
        coloré, cerclé de blanc — tuile protégée, jamais proposée pour un quartier."""
        color = RESOURCE_COLORS.get(kind, RESOURCE_COLORS["bonus"])
        if kind == "bonus":
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(at, size * 0.1, size * 0.1)
            return
        r = size * 0.17
        painter.setPen(QPen(QColor("#f5f5f5"), 1))
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([
            QPointF(at.x(), at.y() - r), QPointF(at.x() + r, at.y()),
            QPointF(at.x(), at.y() + r), QPointF(at.x() - r, at.y()),
        ]))

    @staticmethod
    def _draw_icon(painter: QPainter, c: QPointF, size: float, kind: str, font: QFont, existing: bool) -> None:
        if existing:
            # Quartier de la ville : disque sombre cerclé de la couleur de la frontière.
            path = QPainterPath()
            path.addEllipse(c, size * 0.55, size * 0.55)
            painter.fillPath(path, QColor(20, 22, 28, 170))
            painter.setPen(QPen(QColor(BORDER_COLOR), 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(c, size * 0.55, size * 0.55)
        painter.setFont(font)
        painter.setPen(QColor("#f5f5f5"))
        painter.drawText(
            QRectF(c.x() - size, c.y() - size * 0.6, 2 * size, size * 1.1),
            Qt.AlignCenter, DISTRICT_ICONS.get(kind, kind if kind == NATURAL_WONDER_ICON else "■"),
        )
