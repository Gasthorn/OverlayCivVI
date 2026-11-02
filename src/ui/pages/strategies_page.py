"""Page Stratégies : choisir la stratégie à suivre (spec 03 §4.2).

Affichée d'office en début de partie tant qu'aucune stratégie n'est suivie ; le choix
est envoyé au moteur (`follow_strategy`, spec 04 §4).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

ICONS = {
    "horse": "🐎",
    "coin": "💰",
    "flask": "🔬",
    "scroll": "📜",
    "shield": "🛡️",
    "dove": "🕊️",
    "anchor": "⚓",
}
FACTORS_SHOWN = 3


class StrategiesPage(QWidget):
    follow_requested = Signal(object)  # id de stratégie, ou None pour ne plus en suivre

    def __init__(self) -> None:
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)

        self._prompt = QLabel()
        self._prompt.setObjectName("prompt")
        self._prompt.setWordWrap(True)
        self._layout.addWidget(self._prompt)

        self._cards = QWidget()
        self._cards_layout = QVBoxLayout(self._cards)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(4)
        self._layout.addWidget(self._cards)

    def update_page(self, strategies: list[dict[str, Any]], followed: str | None) -> None:
        followed_label = next((s["label"] for s in strategies if s["id"] == followed), None)
        if followed_label:
            self._prompt.setText(f"Stratégie suivie : {followed_label}. Choisissez-en une autre pour changer de plan.")
        else:
            self._prompt.setText(
                "Choisissez une stratégie pour cette partie : les actions recommandées s'y adapteront."
            )

        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for strategy in sorted(strategies, key=lambda s: -s["score"]):
            self._cards_layout.addWidget(self._card(strategy, strategy["id"] == followed))

    def _card(self, strategy: dict[str, Any], is_followed: bool) -> QWidget:
        card = QFrame()
        card.setObjectName("strategyCardFollowed" if is_followed else "strategyCard")
        grid = QGridLayout(card)
        grid.setContentsMargins(6, 4, 6, 4)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(1)

        icon = QLabel(ICONS.get(strategy.get("icon", ""), "•"))
        icon.setObjectName("actionIcon")
        name = QLabel(strategy["label"])
        name.setObjectName("strategyNameFollowed" if is_followed else "strategyName")
        percent = round(strategy["score"] * 100)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(percent)
        bar.setFormat(f"{percent} %")
        bar.setObjectName("strategyBar")
        button = QPushButton("★ Suivie" if is_followed else "Suivre")
        button.setObjectName("followButtonActive" if is_followed else "followButton")
        button.setToolTip("Ne plus suivre" if is_followed else "Suivre cette stratégie")
        button.clicked.connect(
            lambda _=False, sid=strategy["id"], on=is_followed: self.follow_requested.emit(None if on else sid)
        )

        grid.addWidget(icon, 0, 0)
        grid.addWidget(name, 0, 1)
        grid.addWidget(bar, 0, 2)
        grid.addWidget(button, 0, 3)
        for row, factor in enumerate(strategy.get("factors", [])[:FACTORS_SHOWN], start=1):
            label = QLabel(f"• {factor}")
            label.setObjectName("actionReason")
            label.setWordWrap(True)
            grid.addWidget(label, row, 1, 1, 3)
        grid.setColumnStretch(2, 1)
        return card
