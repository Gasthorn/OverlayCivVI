"""Page Jalons : événements passés et échéances à venir, alimentée par `milestones` (spec 03 §4.3)."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class MilestonesPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)

    def update_page(self, milestones: list[dict[str, Any]]) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        if not milestones:
            empty = QLabel("Aucun jalon pour l'instant")
            empty.setObjectName("actionReason")
            self._layout.addWidget(empty)
            return

        for milestone in milestones:
            is_upcoming = milestone["status"] == "upcoming"
            prefix = "▶ " if is_upcoming else ""
            label = QLabel(f"{prefix}Tour {milestone['turn']} · {milestone['label']}")
            label.setObjectName("milestoneUpcoming" if is_upcoming else "milestoneDone")
            label.setWordWrap(True)
            self._layout.addWidget(label)
