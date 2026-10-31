"""Point d'entrée de l'overlay : python src/ui/main.py (spec 03)."""

from __future__ import annotations

import logging
import os
import signal
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from ui.hotkeys import MOD_ALT, MOD_CONTROL, GlobalHotkeys
from ui.overlay_window import OverlayWindow
from ui.settings import UiSettings
from ui.ws_client import EngineClient

STYLESHEET = Path(__file__).resolve().parent / "styles" / "dark.qss"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s : %(message)s")
    # Qt n'intercepte pas Ctrl+C : on rend le signal à son comportement par défaut.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET.read_text(encoding="utf-8"))

    window = OverlayWindow(UiSettings.load())

    hotkeys = GlobalHotkeys()
    app.installNativeEventFilter(hotkeys)
    hotkeys.register(MOD_CONTROL | MOD_ALT, "O", window.toggle_mode)
    hotkeys.register(MOD_CONTROL | MOD_ALT, "H", window.toggle_visibility)
    hotkeys.register(MOD_CONTROL | MOD_ALT, "P", window.next_page)
    hotkeys.register(MOD_CONTROL | MOD_ALT, "V", window.next_city)
    app.aboutToQuit.connect(hotkeys.unregister_all)

    port = os.environ.get("CIVOVL_WS_PORT", "8765")
    client = EngineClient(f"ws://127.0.0.1:{port}")
    client.connecting.connect(window.on_connecting)
    client.status_received.connect(window.on_status)
    client.recommendations_received.connect(window.on_recommendations)
    window.follow_requested.connect(client.follow_strategy)

    window.show()
    client.open()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
