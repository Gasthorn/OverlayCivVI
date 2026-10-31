"""Fenêtre overlay : flags, modes d'interaction, pages, persistance (spec 03 §3 et §4)."""

from __future__ import annotations

from enum import Enum
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

from ui.pages.actions_page import ActionsPage
from ui.pages.cities_page import CitiesPage
from ui.pages.milestones_page import MilestonesPage
from ui.pages.settle_page import SettlePage
from ui.pages.strategies_page import StrategiesPage
from ui.settings import UiSettings

_STATUS_TEXT = {
    "connecting": "Connexion au service moteur…",
    "waiting_for_game": "En attente d'une partie",
    "ok": "",
    "degraded": "Mode dégradé",
}

# Ordre des onglets (et de Ctrl+Alt+P).
PAGES = (
    ("actions", "Actions"), ("strategies", "Stratégies"), ("cities", "Villes"), ("settle", "Colonisation"),
    ("milestones", "Jalons"),
)


class Mode(Enum):
    CLICK_THROUGH = "click_through"
    INTERACTIVE = "interactive"


class OverlayWindow(QWidget):
    follow_requested = Signal(object)  # id de stratégie, ou None pour ne plus en suivre

    def __init__(self, settings: UiSettings) -> None:
        super().__init__()
        self._settings = settings
        self._mode = Mode.CLICK_THROUGH
        self._connection_state = "connecting"
        self._status_detail: str | None = None
        self._status_turn: int | None = None
        self._reco_turn: int | None = None
        self._game_id: str | None = None
        self._followed: str | None = None
        self._current_index = 0
        self._auto_interactive = False  # mode interactif activé par l'overlay, pas par le joueur

        self.setWindowTitle("Civ VI Smart Overlay")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowOpacity(settings.opacity)
        self.setGeometry(settings.x, settings.y, settings.width, settings.height)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._save_geometry)

        self._build()
        self._apply_mode()

    # --- Construction --------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._root = QFrame()
        self._root.setObjectName("root")
        outer.addWidget(self._root)

        layout = QVBoxLayout(self._root)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        # En-tête : onglets des pages, puis bouton de fermeture (mode interactif).
        header = QHBoxLayout()
        header.setSpacing(4)
        self._tabs = QButtonGroup(self)
        self._tabs.setExclusive(True)
        for index, (key, label) in enumerate(PAGES):
            tab = QPushButton(label)
            tab.setObjectName("pageTab")
            tab.setCheckable(True)
            self._tabs.addButton(tab, index)
            header.addWidget(tab)
        self._tabs.idClicked.connect(self._show_index)
        header.addStretch(1)
        self._close_button = QPushButton("×")
        self._close_button.setObjectName("close")
        self._close_button.setToolTip("Quitter l'overlay")
        # Une fenêtre Qt.Tool ne déclenche pas quitOnLastWindowClosed : on quitte explicitement.
        self._close_button.clicked.connect(QApplication.quit)
        header.addWidget(self._close_button)
        layout.addLayout(header)

        self._status_label = QLabel()
        self._status_label.setObjectName("status")
        layout.addWidget(self._status_label)

        self._actions_page = ActionsPage(self._settings.collapsed.get("other_actions", True))
        self._actions_page.choose_strategy_requested.connect(lambda: self.show_page("strategies"))
        self._actions_page.others_toggled.connect(self._on_section_toggled)
        self._actions_page.content_resized.connect(self._schedule_fit_height)
        self._strategies_page = StrategiesPage()
        self._strategies_page.follow_requested.connect(self.follow_requested)
        self._cities_page = CitiesPage(
            self._settings.show_locked_districts, self._settings.layout_limit,
            self._settings.collapsed.get("city_legend", False),
        )
        self._cities_page.show_locked_changed.connect(self._on_show_locked_changed)
        self._cities_page.layout_limit_changed.connect(self._on_layout_limit_changed)
        self._cities_page.legend_toggled.connect(self._on_section_toggled)
        self._settle_page = SettlePage()
        self._milestones_page = MilestonesPage()

        # Pages empilées « à la main » : une seule visible. Contrairement à QStackedWidget,
        # les pages masquées ne comptent pas dans la hauteur, et la fenêtre rétrécit.
        self._pages_frame = QFrame()
        self._pages_frame.setObjectName("pages")
        pages_layout = QVBoxLayout(self._pages_frame)
        pages_layout.setContentsMargins(0, 4, 0, 0)
        self._pages: tuple[QWidget, ...] = (
            self._actions_page, self._strategies_page, self._cities_page, self._settle_page, self._milestones_page,
        )
        for page in self._pages:
            pages_layout.addWidget(page)
        layout.addWidget(self._pages_frame)
        layout.addStretch(1)  # l'éventuel surplus de hauteur va en bas, pas entre les lignes

        self._size_grip = QSizeGrip(self._root)
        layout.addWidget(self._size_grip, 0, Qt.AlignBottom | Qt.AlignRight)

        self._show_index(0)
        self.on_connecting()

    # --- Pages (spec 03 §4) ---------------------------------------------------

    def show_page(self, key: str) -> None:
        self._show_index(next(i for i, (k, _) in enumerate(PAGES) if k == key))

    def next_page(self) -> None:
        self._show_index((self._current_index + 1) % len(PAGES))

    def next_city(self) -> None:
        """Ville suivante (Ctrl+Alt+V) : ouvre la page Villes si elle n'est pas affichée."""
        if self.current_page() != "cities":
            self.show_page("cities")
        else:
            self._cities_page.next_city()

    def current_page(self) -> str:
        return PAGES[self._current_index][0]

    def _show_index(self, index: int) -> None:
        self._current_index = index
        self._tabs.button(index).setChecked(True)
        for i, page in enumerate(self._pages):
            page.setVisible(i == index)
        self._schedule_fit_height()

    def _update_auto_page(self, game_id: str | None, followed: str | None) -> None:
        """Nouvelle partie, ou changement de stratégie suivie : page Actions si une stratégie est
        suivie, sinon page Stratégies pour en choisir une. Le reste du temps, la page ne bouge pas.

        Pendant l'attente du choix, l'overlay passe de lui-même en mode interactif (sinon le bouton
        « Suivre » n'est pas cliquable), puis revient en click-through une fois la stratégie choisie,
        sauf si le joueur a changé de mode entre-temps.
        """
        if game_id != self._game_id or followed != self._followed:
            if followed:
                self.show_page("actions")
                if self._auto_interactive:
                    self._auto_interactive = False
                    self._set_mode(Mode.CLICK_THROUGH)
            else:
                self.show_page("strategies")
                if self._mode is Mode.CLICK_THROUGH:
                    self._auto_interactive = True
                    self._set_mode(Mode.INTERACTIVE)
        self._game_id, self._followed = game_id, followed

    # --- Modes (spec 03 §3.2) -----------------------------------------------

    def toggle_mode(self) -> None:
        """Changement manuel (Ctrl+Alt+O) : il prime sur le mode choisi automatiquement."""
        self._auto_interactive = False
        self._set_mode(Mode.INTERACTIVE if self._mode is Mode.CLICK_THROUGH else Mode.CLICK_THROUGH)

    def mode(self) -> Mode:
        return self._mode

    def _set_mode(self, mode: Mode) -> None:
        if mode is not self._mode:
            self._mode = mode
            self._apply_mode()

    def toggle_visibility(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()

    def _apply_mode(self) -> None:
        interactive = self._mode is Mode.INTERACTIVE
        was_visible = self.isVisible()
        # Changer un flag masque la fenêtre : il faut la réafficher.
        self.setWindowFlag(Qt.WindowTransparentForInput, not interactive)
        self._close_button.setVisible(interactive)
        self._size_grip.setVisible(interactive)
        self._root.setProperty("interactive", interactive)
        self._repolish(self._root)
        if was_visible:
            self.show()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (API Qt)
        if self._mode is Mode.INTERACTIVE and event.button() == Qt.LeftButton:
            self.windowHandle().startSystemMove()
        super().mousePressEvent(event)

    # --- Persistance ---------------------------------------------------------

    def moveEvent(self, event) -> None:  # noqa: N802 (API Qt)
        super().moveEvent(event)
        self._save_timer.start()

    def resizeEvent(self, event) -> None:  # noqa: N802 (API Qt)
        super().resizeEvent(event)
        self._save_timer.start()

    def _save_geometry(self) -> None:
        geometry = self.geometry()
        self._settings.x, self._settings.y = geometry.x(), geometry.y()
        self._settings.width, self._settings.height = geometry.width(), geometry.height()
        self._settings.save()

    def _on_section_toggled(self, key: str, collapsed: bool) -> None:
        self._settings.collapsed[key] = collapsed
        self._settings.save()
        self._schedule_fit_height()

    def _on_show_locked_changed(self, show: bool) -> None:
        self._settings.show_locked_districts = show
        self._settings.save()
        self._schedule_fit_height()

    def _on_layout_limit_changed(self, limit: int) -> None:
        self._settings.layout_limit = limit
        self._settings.save()
        self._schedule_fit_height()

    def _schedule_fit_height(self) -> None:
        QTimer.singleShot(0, self._fit_height)

    def _fit_height(self) -> None:
        """La hauteur suit le contenu ; la largeur reste celle choisie par le joueur.

        Les textes à retour à la ligne dépendent de la largeur : sizeHint() les surestime.
        """
        layout = self.layout()
        width = self.width()
        if layout.hasHeightForWidth():
            height = layout.totalHeightForWidth(width)
        else:
            height = layout.totalSizeHint().height()
        self.resize(width, max(height, layout.totalMinimumSize().height()))

    # --- Données (spec 03 §3.3 et §4) ---------------------------------------

    def on_connecting(self) -> None:
        self._connection_state = "connecting"
        self._status_detail = None
        self._refresh_status()

    def on_status(self, message: dict[str, Any]) -> None:
        self._connection_state = message["state"]
        self._status_detail = message.get("detail")
        self._status_turn = message.get("turn")
        self._refresh_status()

    def on_recommendations(self, message: dict[str, Any]) -> None:
        followed = message.get("followed_strategy")
        self._reco_turn = message["turn"]
        self._actions_page.update_page(message["actions"], message["strategies"], followed)
        self._strategies_page.update_page(message["strategies"], followed)
        self._cities_page.update_page(message.get("cities", []))
        self._settle_page.update_page(message.get("settle"))
        self._milestones_page.update_page(message["milestones"])
        self._update_auto_page(message.get("game_id"), followed)
        self._refresh_status()
        self._schedule_fit_height()

    def _refresh_status(self) -> None:
        stale = (
            self._status_turn is not None
            and self._reco_turn is not None
            and self._reco_turn < self._status_turn
        )
        text = _STATUS_TEXT.get(self._connection_state, self._connection_state)
        if self._connection_state == "degraded" and self._status_detail:
            text = f"{text} : {self._status_detail}"
        elif stale and self._connection_state == "ok":
            text = "En attente d'analyse"
        self._status_label.setText(text)
        self._status_label.setVisible(bool(text))
        if self._root.property("stale") != stale:
            self._root.setProperty("stale", stale)
            self._repolish(self._root)

    @staticmethod
    def _repolish(root: QWidget) -> None:
        """Réapplique la feuille de style après le changement d'une propriété dynamique."""
        style = root.style()
        for widget in (root, *root.findChildren(QWidget)):
            style.unpolish(widget)
            style.polish(widget)
