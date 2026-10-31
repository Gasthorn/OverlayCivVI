"""Serveur WebSocket local : diffuse vers l'overlay et reçoit ses commandes (spec 04)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from websockets.asyncio.server import Server, ServerConnection, broadcast, serve
from websockets.exceptions import ConnectionClosed

import contracts

log = logging.getLogger(__name__)


class Broadcaster:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._server: Server | None = None
        self._clients: set[ServerConnection] = set()
        self._last: dict[str, str] = {}  # dernier message sérialisé, par type
        self.on_client_message: Callable[[dict[str, Any]], None] | None = None

    async def start(self) -> None:
        self._server = await serve(self._handle, self.host, self.port)
        # Port effectif (utile quand port=0 dans les tests).
        self.port = next(iter(self._server.sockets)).getsockname()[1]
        log.info("WebSocket en écoute sur ws://%s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    def publish(self, message: dict[str, Any]) -> None:
        error = contracts.first_error("recommendations", message)
        if error is not None:
            log.error("Message %s non conforme, non publié : %s", message.get("type"), error)
            return
        text = json.dumps(message, ensure_ascii=False)
        self._last[message["type"]] = text
        broadcast(self._clients, text)

    async def _handle(self, connection: ServerConnection) -> None:
        self._clients.add(connection)
        log.info("Overlay connecté (%d client(s))", len(self._clients))
        try:
            for message_type in ("status", "recommendations"):
                if message_type in self._last:
                    await connection.send(self._last[message_type])
            async for text in connection:
                self._receive(text)
        except ConnectionClosed:
            pass
        finally:
            self._clients.discard(connection)
            log.info("Overlay déconnecté (%d client(s))", len(self._clients))

    def _receive(self, text: str | bytes) -> None:
        """Message de l'overlay (spec 04 §4) : validé, puis transmis au service."""
        try:
            message = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.warning("Message client illisible ignoré : %s", exc)
            return
        error = contracts.first_error("client_messages", message)
        if error is not None:
            log.warning("Message client non conforme ignoré : %s", error)
            return
        if self.on_client_message is not None:
            try:
                self.on_client_message(message)
            except Exception:
                log.exception("Traitement du message client %s en échec", message.get("type"))
