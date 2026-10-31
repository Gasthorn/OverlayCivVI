"""Panel repliable : un clic sur l'en-tête (mode interactif) masque ou affiche le contenu."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout, QWidget


class CollapsiblePanel(QFrame):
    toggled = Signal(str, bool)  # (clé du panel, replié)

    def __init__(self, key: str, title: str, collapsed: bool = False) -> None:
        super().__init__()
        self.key = key
        self._title = title
        self._suffix = ""
        self.setObjectName("panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(2)

        self._header = QPushButton()
        self._header.setObjectName("panelHeader")
        self._header.clicked.connect(self._toggle)
        layout.addWidget(self._header)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(4, 0, 0, 0)
        self.content_layout.setSpacing(2)
        layout.addWidget(self.content)

        self._set_collapsed(collapsed)

    def set_title_suffix(self, suffix: str) -> None:
        self._suffix = suffix
        self._refresh_header()

    def _toggle(self) -> None:
        self._set_collapsed(not self._collapsed)
        self.toggled.emit(self.key, self._collapsed)

    def _set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self.content.setVisible(not collapsed)
        self._refresh_header()

    def _refresh_header(self) -> None:
        arrow = "▸" if self._collapsed else "▾"
        self._header.setText(f"{arrow} {self._title}{self._suffix}")

    def clear_content(self) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
