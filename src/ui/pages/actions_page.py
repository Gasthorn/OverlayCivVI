"""Page Actions : le plan de la stratégie suivie, les urgences et les autres opportunités (spec 03 §4.1)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ui.panels.collapsible import CollapsiblePanel
from ui.widgets.action_list import ActionList

URGENT_PRIORITY = 80  # même seuil que le moteur (spec 02 §6.5) : actions jamais rétrogradées


class ActionsPage(QWidget):
    choose_strategy_requested = Signal()
    others_toggled = Signal(str, bool)  # (clé, replié) pour la persistance
    content_resized = Signal()

    def __init__(self, others_collapsed: bool = True) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # En-tête : stratégie suivie et bouton pour en changer.
        header = QHBoxLayout()
        self._strategy_label = QLabel()
        self._strategy_label.setObjectName("followedHeader")
        self._strategy_label.setWordWrap(True)
        header.addWidget(self._strategy_label, 1)
        self._change_button = QPushButton()
        self._change_button.setObjectName("linkButton")
        self._change_button.clicked.connect(self.choose_strategy_requested)
        header.addWidget(self._change_button)
        layout.addLayout(header)

        self._urgent_title = _section_title("À faire maintenant")
        self._urgent = ActionList(max_shown=3)
        self._plan_title = _section_title("")
        self._plan = ActionList(max_shown=6, empty_text="Rien de plus à faire pour ce plan ce tour-ci")
        self._others = CollapsiblePanel("other_actions", "Autres opportunités", others_collapsed)
        self._others_list = ActionList(max_shown=5)
        self._others.content_layout.addWidget(self._others_list)
        self._others.toggled.connect(self.others_toggled)

        for widget in (self._urgent_title, self._urgent, self._plan_title, self._plan, self._others):
            layout.addWidget(widget)
        for action_list in (self._urgent, self._plan, self._others_list):
            action_list.resized.connect(self.content_resized)

    def update_page(
        self, actions: list[dict[str, Any]], strategies: list[dict[str, Any]], followed: str | None
    ) -> None:
        strategy = next((s for s in strategies if s["id"] == followed), None)
        if strategy is None:
            self._strategy_label.setText("Aucune stratégie suivie")
            self._change_button.setText("Choisir une stratégie")
            # Sans stratégie, une seule liste : toutes les actions, par priorité.
            self._set_section(self._urgent_title, self._urgent, [])
            self._plan_title.setText("Actions recommandées")
            self._plan_title.show()
            self._plan.set_empty_text("Rien à signaler ce tour-ci")
            self._plan.set_actions(actions)
            self._others.hide()
            return

        self._strategy_label.setText(f"★ {strategy['label']} · {round(strategy['score'] * 100)} %")
        self._change_button.setText("Changer")
        # Sous le titre « Plan : <stratégie> », le préfixe « <stratégie> : » des raisons est redondant.
        prefix = f"{strategy['label']} : "
        plan = [
            {**a, "reason": a["reason"].removeprefix(prefix)}
            for a in actions if a.get("strategy") == followed
        ]
        urgent = [a for a in actions if not a.get("strategy") and a["priority"] >= URGENT_PRIORITY]
        others = [a for a in actions if not a.get("strategy") and a["priority"] < URGENT_PRIORITY]

        self._set_section(self._urgent_title, self._urgent, urgent)
        self._plan_title.setText(f"Plan : {strategy['label']}")
        self._plan_title.show()
        self._plan.set_empty_text("Rien de plus à faire pour ce plan ce tour-ci")
        self._plan.set_actions(plan)
        self._others.set_title_suffix(f" ({len(others)})")
        self._others_list.set_actions(others)
        self._others.setVisible(bool(others))

    @staticmethod
    def _set_section(title: QLabel, action_list: ActionList, actions: list[dict[str, Any]]) -> None:
        title.setVisible(bool(actions))
        action_list.setVisible(bool(actions))
        action_list.set_actions(actions)


def _section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label
