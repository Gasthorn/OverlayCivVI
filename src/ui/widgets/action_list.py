"""Liste d'actions recommandées (spec 03 §4), avec repli au-delà de `max_shown`."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

CATEGORY_ICONS = {
    "research": "🔬",
    "civic": "📜",
    "production": "🏗️",
    "unit": "🛠️",
    "policy": "🏛️",
    "other": "•",
}


class ActionList(QWidget):
    resized = Signal()  # le contenu a changé de hauteur (dépliage « +N »)

    def __init__(self, max_shown: int = 5, empty_text: str = "Rien à signaler ce tour-ci") -> None:
        super().__init__()
        self._max_shown = max_shown
        self._empty_text = empty_text
        self._actions: list[dict[str, Any]] = []
        self._expanded = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)

    def set_empty_text(self, text: str) -> None:
        self._empty_text = text

    def set_actions(self, actions: list[dict[str, Any]]) -> None:
        self._actions = sorted(actions, key=lambda a: -a["priority"])
        self._render()

    def _render(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        if not self._actions:
            empty = QLabel(self._empty_text)
            empty.setObjectName("actionReason")
            self._layout.addWidget(empty)
            return

        shown = self._actions if self._expanded else self._actions[:self._max_shown]
        for action in shown:
            self._layout.addWidget(_action_row(action))

        hidden = len(self._actions) - self._max_shown
        if hidden > 0:
            more = QPushButton("Réduire" if self._expanded else f"+{hidden} autre{'s' if hidden > 1 else ''}")
            more.setObjectName("moreActions")
            more.clicked.connect(self._toggle_expanded)
            self._layout.addWidget(more, 0, Qt.AlignLeft)

    def _toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self._render()
        self.resized.emit()


def _action_row(action: dict[str, Any]) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 2, 0, 2)
    layout.setSpacing(6)

    icon = QLabel(CATEGORY_ICONS.get(action["category"], "•"))
    icon.setObjectName("actionIcon")
    icon.setAlignment(Qt.AlignTop)
    layout.addWidget(icon)

    text = QVBoxLayout()
    text.setSpacing(0)
    title = QLabel(action["title"] + ("  [IA]" if action.get("source") == "llm" else ""))
    # Les actions servant la stratégie suivie ressortent (spec 03 §4).
    title.setObjectName("actionTitleFocus" if action.get("strategy") else "actionTitle")
    title.setWordWrap(True)
    reason = QLabel(action["reason"])
    reason.setObjectName("actionReason")
    reason.setWordWrap(True)
    text.addWidget(title)
    text.addWidget(reason)
    layout.addLayout(text, 1)
    return row
