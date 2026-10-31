"""Page Villes : schéma d'une ville et disposition conseillée des quartiers (spec 03 §4.4)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.panels.collapsible import CollapsiblePanel
from ui.widgets.hex_map import DISTRICT_ICONS, HexMap, is_own_district

STATUS_TEXT = {"now": "maintenant", "later": "plus tard"}
# Nombre de quartiers conseillés affichés (carte et liste) ; 0 = tous.
LAYOUT_LIMITS = ((3, "3 quartiers"), (5, "5 quartiers"), (8, "8 quartiers"), (0, "Tous"))
LEGEND_KEY = "city_legend"
LEGEND_COLUMNS = 2


class CitiesPage(QWidget):
    show_locked_changed = Signal(bool)
    layout_limit_changed = Signal(int)
    legend_toggled = Signal(str, bool)  # (clé, replié) pour la persistance

    def __init__(self, show_locked: bool = False, layout_limit: int = 5, legend_collapsed: bool = False) -> None:
        super().__init__()
        self._cities: list[dict[str, Any]] = []
        self._selected_id: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._combo = QComboBox()
        self._combo.setObjectName("cityCombo")
        self._combo.currentIndexChanged.connect(self._on_selected)
        layout.addWidget(self._combo)

        self._slots = QLabel()
        self._slots.setObjectName("actionReason")
        layout.addWidget(self._slots)

        # Options mémorisées : quartiers pas encore débloqués, nombre de suggestions affichées.
        self._options = QWidget()
        options = QHBoxLayout(self._options)
        options.setContentsMargins(0, 0, 0, 0)
        self._show_locked = QCheckBox("Inclure les quartiers pas encore débloqués")
        self._show_locked.setObjectName("showLocked")
        self._show_locked.setChecked(show_locked)
        self._show_locked.toggled.connect(self._on_show_locked)
        options.addWidget(self._show_locked, 1)
        self._limit = QComboBox()
        self._limit.setObjectName("layoutLimit")
        for value, text in LAYOUT_LIMITS:
            self._limit.addItem(text, value)
        values = [value for value, _ in LAYOUT_LIMITS]
        self._limit.setCurrentIndex(values.index(layout_limit) if layout_limit in values else 1)
        self._limit.currentIndexChanged.connect(self._on_limit)
        options.addWidget(self._limit)
        layout.addWidget(self._options)

        self._map = HexMap()
        layout.addWidget(self._map)

        self._suggestions_host, self._suggestions = self._grid("Quartiers conseillés")
        layout.addWidget(self._suggestions_host)
        self._hidden_count = QLabel()
        self._hidden_count.setObjectName("actionReason")
        layout.addWidget(self._hidden_count)

        self._legend = CollapsiblePanel(LEGEND_KEY, "Légende", legend_collapsed)
        self._legend.toggled.connect(self.legend_toggled)
        self._built_host = QWidget()
        self._built = QGridLayout(self._built_host)
        self._built.setContentsMargins(0, 0, 0, 0)
        self._built.setHorizontalSpacing(8)
        self._built.setVerticalSpacing(1)
        self._legend.content_layout.addWidget(self._built_host)
        self._hint = QLabel(
            "Trait blanc : frontière actuelle de la ville · icône cerclée : quartier de la ville, "
            "estompée : d'une autre ville · cercles en tirets : quartiers conseillés "
            "(en points : pas encore débloqués, 🔒 prérequis) · "
            "losanges : luxe (violet), stratégique (orange) ou site archéologique, jamais recouverts · "
            "hachures : autre civilisation"
        )
        self._hint.setObjectName("actionReason")
        self._hint.setWordWrap(True)
        self._legend.content_layout.addWidget(self._hint)
        layout.addWidget(self._legend)

        self._empty = QLabel("Carte des villes disponible au début du prochain tour")
        self._empty.setObjectName("actionReason")
        layout.addWidget(self._empty)

    @staticmethod
    def _grid(title: str) -> tuple[QWidget, QGridLayout]:
        host = QWidget()
        outer = QVBoxLayout(host)
        outer.setContentsMargins(0, 2, 0, 0)
        outer.setSpacing(1)
        heading = QLabel(title)
        heading.setObjectName("legendTitle")
        outer.addWidget(heading)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(1)
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)
        return host, grid

    @staticmethod
    def _clear(grid: QGridLayout) -> None:
        while grid.count():
            item = grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    @staticmethod
    def built_districts(city: dict[str, Any]) -> list[tuple[str, str]]:
        """(type générique, nom) de chaque sorte de quartier construit sur la carte, une seule fois
        même s'il apparaît plusieurs fois ; le nom vient de préférence d'un quartier de la ville."""
        tiles = sorted(
            (t for t in city["tiles"] if t.get("district")), key=lambda t: not is_own_district(t)
        )
        rows: dict[str, str] = {}
        for tile in tiles:
            rows.setdefault(tile["district"], tile.get("district_label") or tile["district"])
        return list(rows.items())

    def update_page(self, cities: list[dict[str, Any]]) -> None:
        self._cities = cities
        self._combo.blockSignals(True)
        self._combo.clear()
        for city in cities:
            self._combo.addItem(f"{city['name']} ({city.get('population', '?')})", city["city_id"])
        ids = [c["city_id"] for c in cities]
        index = ids.index(self._selected_id) if self._selected_id in ids else 0
        self._combo.setCurrentIndex(index if cities else -1)
        self._combo.blockSignals(False)
        self._on_selected(self._combo.currentIndex())

    def next_city(self) -> None:
        if self._cities:
            self._combo.setCurrentIndex((self._combo.currentIndex() + 1) % len(self._cities))

    def selected_city(self) -> dict[str, Any] | None:
        index = self._combo.currentIndex()
        return self._cities[index] if 0 <= index < len(self._cities) else None

    def _on_show_locked(self, checked: bool) -> None:
        self.show_locked_changed.emit(checked)
        self._on_selected(self._combo.currentIndex())

    def _on_limit(self, index: int) -> None:
        self.layout_limit_changed.emit(self._limit.itemData(index))
        self._on_selected(self._combo.currentIndex())

    def visible_layout(self, city: dict[str, Any]) -> list[dict[str, Any]]:
        """Quartiers affichés : les quartiers pas encore débloqués seulement si la case est cochée."""
        if self._show_locked.isChecked():
            return city["layout"]
        return [entry for entry in city["layout"] if entry.get("unlocked", True)]

    def _on_selected(self, index: int) -> None:
        city = self.selected_city()
        has_city = city is not None
        for widget in (self._combo, self._slots, self._options, self._map, self._suggestions_host, self._legend):
            widget.setVisible(has_city)
        self._empty.setVisible(not has_city)
        if city is None:
            self._hidden_count.setVisible(False)
            return
        self._selected_id = city["city_id"]
        candidates = self.visible_layout(city)
        limit = self._limit.currentData() or len(candidates)
        layout_entries = candidates[:limit]
        self._map.set_city(city | {"layout": layout_entries})

        slots = city.get("slots")
        if slots:
            free = max(0, slots["allowed"] - slots["used"])
            self._slots.setText(
                f"Quartiers : {slots['used']}/{slots['allowed']} · "
                f"{free} emplacement{'s' if free > 1 else ''} libre{'s' if free > 1 else ''}"
            )
        else:
            self._slots.setText("")

        self._clear(self._suggestions)
        if not layout_entries:
            none = QLabel("Aucun quartier à placer pour l'instant")
            none.setObjectName("actionReason")
            self._suggestions.addWidget(none, 0, 0, 1, 4)
        for row, entry in enumerate(layout_entries):
            later = entry["status"] == "later"
            icon = QLabel(DISTRICT_ICONS.get(entry["kind"], "■"))
            icon.setObjectName("actionIcon")
            # ★ : quartier de la stratégie suivie (prioritaire sur sa meilleure case).
            name = QLabel(("★ " if entry.get("focus") else "") + entry["label"])
            name.setObjectName("layoutLater" if later else "layoutNow")
            adjacency = QLabel(f"{entry['adjacency']:+g}")
            adjacency.setObjectName("layoutLater" if later else "layoutNow")
            status_text = STATUS_TEXT.get(entry["status"], entry["status"])
            if entry.get("wonder"):
                status_text = "merveille, maintenant"
            elif entry.get("unlocked") is False:
                status_text = f"🔒 {entry.get('requires') or 'non débloqué'}"
            elif entry.get("uses_slot") is False:
                status_text += " (hors quota)"
            status = QLabel(status_text)
            status.setObjectName("actionReason")
            for column, widget in enumerate((icon, name, adjacency, status)):
                self._suggestions.addWidget(widget, row, column)
        hidden = len(candidates) - len(layout_entries)
        self._hidden_count.setText(f"+{hidden} autre{'s' if hidden > 1 else ''} quartier{'s' if hidden > 1 else ''} masqué{'s' if hidden > 1 else ''}")
        self._hidden_count.setVisible(hidden > 0)

        # Légende des icônes des quartiers déjà construits : une entrée par sorte de quartier.
        self._clear(self._built)
        built = self.built_districts(city)
        self._built_host.setVisible(bool(built))
        for i, (kind, label) in enumerate(built):
            row, pair = divmod(i, LEGEND_COLUMNS)
            icon = QLabel(DISTRICT_ICONS.get(kind, "■"))
            icon.setObjectName("actionIcon")
            name = QLabel(label)
            name.setObjectName("layoutBuilt")
            self._built.addWidget(icon, row, 2 * pair)
            self._built.addWidget(name, row, 2 * pair + 1)
        for pair in range(LEGEND_COLUMNS):
            self._built.setColumnStretch(2 * pair + 1, 1)
