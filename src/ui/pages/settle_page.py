"""Page Colonisation : sites conseillés pour fonder une ville sur la partie découverte (spec 03 §4.5)."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from ui.widgets.hex_map import HexMap

MAP_HEIGHT = 300


class SettlePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._intro = QLabel("Sites conseillés pour une nouvelle ville, sur la partie découverte de la carte")
        self._intro.setObjectName("actionReason")
        self._intro.setWordWrap(True)
        layout.addWidget(self._intro)

        self._map = HexMap(MAP_HEIGHT)
        layout.addWidget(self._map)

        self._sites_host = QWidget()
        self._sites = QGridLayout(self._sites_host)
        self._sites.setContentsMargins(0, 0, 0, 0)
        self._sites.setHorizontalSpacing(8)
        self._sites.setVerticalSpacing(2)
        self._sites.setColumnStretch(2, 1)
        layout.addWidget(self._sites_host)

        self._hint = QLabel(
            "Cercles numérotés : sites conseillés (n°1 doré) · trait blanc : votre territoire · "
            "hachures : territoire étranger · 🏞️ merveille naturelle · losanges : luxe (violet), "
            "stratégique (orange)"
        )
        self._hint.setObjectName("actionReason")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self._empty = QLabel("Carte de colonisation disponible au début du prochain tour")
        self._empty.setObjectName("actionReason")
        layout.addWidget(self._empty)

    @staticmethod
    def map_data(settle: dict[str, Any]) -> dict[str, Any]:
        """Données de la carte : les sites deviennent des repères numérotés (cercle doré pour le n°1)."""
        markers = [
            {
                "hex_x": s["hex_x"], "hex_y": s["hex_y"], "kind": "DISTRICT_CITY_CENTER",
                "status": "now" if s["rank"] == 1 else "later", "adjacency": s["score"], "caption": f"n°{s['rank']}",
            }
            for s in settle["sites"]
        ]
        return {"tiles": settle["tiles"], "layout": markers}

    def update_page(self, settle: dict[str, Any] | None) -> None:
        has_map = bool(settle and settle.get("tiles"))
        for widget in (self._intro, self._map, self._sites_host, self._hint):
            widget.setVisible(has_map)
        self._empty.setVisible(not has_map)

        while self._sites.count():
            item = self._sites.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if not has_map:
            self._map.set_city(None)
            return
        self._map.set_city(self.map_data(settle))

        if not settle["sites"]:
            none = QLabel("Aucun site libre à distance raisonnable de vos villes")
            none.setObjectName("actionReason")
            self._sites.addWidget(none, 0, 0, 1, 3)
        for row, site in enumerate(settle["sites"]):
            rank = QLabel(f"n°{site['rank']}")
            rank.setObjectName("layoutNow" if site["rank"] == 1 else "layoutLater")
            score = QLabel(f"{site['score']:+g}")
            score.setObjectName("layoutNow" if site["rank"] == 1 else "layoutLater")
            reasons = list(site["reasons"])
            if site.get("nearest_city"):
                reasons.append(f"à {site['distance']} tuiles de {site['nearest_city']}")
            text = QLabel(" · ".join(dict.fromkeys(reasons)))
            text.setObjectName("actionReason")
            text.setWordWrap(True)
            for column, widget in enumerate((rank, score, text)):
                self._sites.addWidget(widget, row, column)
