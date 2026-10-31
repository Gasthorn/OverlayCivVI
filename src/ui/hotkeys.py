"""Raccourcis globaux via RegisterHotKey (Win32), sans hook clavier (spec 03 §3.2)."""

from __future__ import annotations

import ctypes
import logging
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

log = logging.getLogger(__name__)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

_user32 = ctypes.windll.user32
_user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.UnregisterHotKey.restype = wintypes.BOOL


class GlobalHotkeys(QAbstractNativeEventFilter):
    """Raccourcis enregistrés au niveau du thread (hWnd NULL).

    Le hWnd de la fenêtre change quand Qt la recrée (changement de flags), d'où ce choix.
    """

    def __init__(self) -> None:
        super().__init__()
        self._callbacks: dict[int, Callable[[], None]] = {}

    def register(self, modifiers: int, key: str, callback: Callable[[], None]) -> bool:
        hotkey_id = len(self._callbacks) + 1
        if not _user32.RegisterHotKey(None, hotkey_id, modifiers | MOD_NOREPEAT, ord(key.upper())):
            log.warning("Raccourci %s indisponible (déjà utilisé par une autre application ?)", key)
            return False
        self._callbacks[hotkey_id] = callback
        return True

    def unregister_all(self) -> None:
        for hotkey_id in self._callbacks:
            _user32.UnregisterHotKey(None, hotkey_id)
        self._callbacks.clear()

    def nativeEventFilter(self, event_type, message):  # noqa: N802 (API Qt)
        if bytes(event_type) in (b"windows_dispatcher_MSG", b"windows_generic_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and not msg.hWnd:
                callback = self._callbacks.get(msg.wParam)
                if callback is not None:
                    callback()
                    return True, 0
        return False, 0
