"""Client WebSocket vers le service moteur, intégré à la boucle Qt (spec 03 §3.3)."""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtWebSockets import QWebSocket

import contracts

log = logging.getLogger(__name__)

_BACKOFF_S = (1, 2, 4, 10)


class EngineClient(QObject):
    connecting = Signal()
    status_received = Signal(dict)
    recommendations_received = Signal(dict)

    def __init__(self, url: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._url = QUrl(url)
        self._attempt = 0
        self._socket = QWebSocket()
        self._socket.connected.connect(self._on_connected)
        self._socket.disconnected.connect(self._schedule_reconnect)
        self._socket.errorOccurred.connect(self._schedule_reconnect)
        self._socket.textMessageReceived.connect(self._on_message)
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self.open)

    def open(self) -> None:
        self.connecting.emit()
        self._socket.open(self._url)

    def follow_strategy(self, strategy_id: str | None) -> None:
        """Demande au moteur de suivre une stratégie, ou d'arrêter (spec 04 §4)."""
        message = {"type": "follow_strategy", "schema_version": 1, "strategy_id": strategy_id}
        if not self._socket.isValid():
            log.warning("Moteur non connecté : choix de stratégie non transmis")
            return
        self._socket.sendTextMessage(json.dumps(message))

    def _on_connected(self) -> None:
        log.info("Connecté à %s", self._url.toString())
        self._attempt = 0

    def _schedule_reconnect(self, *_: object) -> None:
        # disconnected et errorOccurred peuvent arriver tous les deux pour un même échec.
        if self._retry_timer.isActive():
            return
        self.connecting.emit()
        delay = _BACKOFF_S[min(self._attempt, len(_BACKOFF_S) - 1)]
        self._attempt += 1
        self._retry_timer.start(delay * 1000)

    def _on_message(self, text: str) -> None:
        try:
            message = json.loads(text)
        except json.JSONDecodeError as exc:
            log.warning("Message illisible ignoré : %s", exc)
            return
        error = contracts.first_error("recommendations", message)
        if error is not None:
            log.warning("Message non conforme ignoré : %s", error)
            return
        if message["type"] == "status":
            self.status_received.emit(message)
        else:
            self.recommendations_received.emit(message)
