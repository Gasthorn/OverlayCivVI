"""Lecture incrémentale de Lua.log et réassemblage des messages [CIVOVL] (spec 01 §4, spec 02 §3)."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# Le jeu préfixe chaque ligne par le nom du contexte : le marqueur est cherché n'importe où.
MARKER_RE = re.compile(rb"\[CIVOVL\] (\d+) (\d+)/(\d+) (.*)$")


@dataclass
class _PendingMessage:
    msg_id: int
    total: int
    last_seen: float
    parts: dict[int, bytes] = field(default_factory=dict)


class FragmentAssembler:
    """Réassemble les fragments d'un message.

    Travaille en octets : un fragment peut couper un caractère UTF-8 multi-octets,
    le décodage n'a lieu qu'une fois le message complet.
    """

    def __init__(self, timeout_s: float = 10.0, clock: Callable[[], float] = time.monotonic) -> None:
        self._timeout_s = timeout_s
        self._clock = clock
        self._pending: _PendingMessage | None = None

    def feed_line(self, line: bytes) -> bytes | None:
        """Traite une ligne de log ; retourne le JSON complet quand le dernier fragment arrive."""
        match = MARKER_RE.search(line.rstrip(b"\r\n"))
        if match is None:
            return None

        msg_id, part, total = (int(g) for g in match.group(1, 2, 3))
        payload = match.group(4)
        if total < 1 or not 1 <= part <= total:
            log.warning("Fragment invalide ignoré (msg_id=%d, %d/%d)", msg_id, part, total)
            return None

        now = self._clock()
        pending = self._pending
        if pending is not None and (
            pending.msg_id != msg_id
            or pending.total != total
            or part in pending.parts  # msg_id réutilisé après un rechargement du mod
            or now - pending.last_seen > self._timeout_s
        ):
            log.warning(
                "Message incomplet abandonné (msg_id=%d, %d/%d fragments)",
                pending.msg_id, len(pending.parts), pending.total,
            )
            pending = None

        if pending is None:
            pending = _PendingMessage(msg_id=msg_id, total=total, last_seen=now)
        pending.parts[part] = payload
        pending.last_seen = now

        if len(pending.parts) < total:
            self._pending = pending
            return None

        self._pending = None
        return b"".join(pending.parts[i] for i in range(1, total + 1))


class LuaLogTailer:
    """Suit Lua.log, y compris quand le jeu le tronque ou le recrée au lancement."""

    def __init__(self, path: Path, assembler: FragmentAssembler | None = None) -> None:
        self.path = path
        self._assembler = assembler or FragmentAssembler()
        self._position = 0
        self._file_id: int | None = None
        self._partial_line = b""
        self._missing_logged = False

    def _reset(self) -> None:
        self._position = 0
        self._partial_line = b""

    def poll(self) -> list[bytes]:
        """Lit les nouvelles lignes et retourne les messages complets (JSON brut en octets)."""
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            if not self._missing_logged:
                log.info("En attente de %s", self.path)
                self._missing_logged = True
            self._file_id = None
            self._reset()
            return []
        self._missing_logged = False

        if self._file_id is not None and stat.st_ino != self._file_id:
            log.info("Lua.log recréé, relecture depuis le début")
            self._reset()
        elif stat.st_size < self._position:
            log.info("Lua.log tronqué, relecture depuis le début")
            self._reset()
        self._file_id = stat.st_ino

        if stat.st_size == self._position:
            return []

        with self.path.open("rb") as f:
            f.seek(self._position)
            chunk = f.read()
        self._position += len(chunk)

        lines = (self._partial_line + chunk).split(b"\n")
        self._partial_line = lines.pop()

        messages = []
        for line in lines:
            message = self._assembler.feed_line(line)
            if message is not None:
                messages.append(message)
        return messages
