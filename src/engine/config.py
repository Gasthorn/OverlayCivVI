"""Configuration du service moteur, surchargeable par variables d'environnement."""

from __future__ import annotations

import ctypes
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# FOLDERID_Documents : suit la redirection éventuelle vers OneDrive.
_FOLDERID_DOCUMENTS = uuid.UUID("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}")


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def documents_dir() -> Path:
    """Dossier « Documents » de Windows, tel que Civ VI le résout."""
    if os.name == "nt":
        guid = _GUID.from_buffer_copy(_FOLDERID_DOCUMENTS.bytes_le)
        path_ptr = ctypes.c_wchar_p()
        result = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(path_ptr)
        )
        if result == 0 and path_ptr.value:
            path = Path(path_ptr.value)
            ctypes.windll.ole32.CoTaskMemFree(path_ptr)
            return path
    return Path.home() / "Documents"


def civ6_user_dir() -> Path:
    """Dossier des mods et sauvegardes."""
    return documents_dir() / "My Games" / "Sid Meier's Civilization VI"


def civ6_app_data_dir() -> Path:
    """Dossier des logs, du cache (DebugGameplay.sqlite) et d'AppOptions.txt.

    Les versions récentes du jeu l'ont déplacé vers %LOCALAPPDATA% ; repli sur Documents sinon.
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidate = Path(local_app_data) / "Firaxis Games" / "Sid Meier's Civilization VI"
        if candidate.is_dir():
            return candidate
    return civ6_user_dir()


CIV6_STEAM_APP_ID = 289070


def civ6_install_dir() -> Path | None:
    """Dossier d'installation du jeu (traductions des DLC), d'après la clé de désinstallation Steam."""
    if os.name != "nt":
        return None
    import winreg

    key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App {CIV6_STEAM_APP_ID}"
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_READ | view) as key:
                location, _ = winreg.QueryValueEx(key, "InstallLocation")
        except OSError:
            continue
        if location and Path(location).is_dir():
            return Path(location)
    return None


def game_language(app_data: Path, default: str = "fr_FR") -> str:
    """Langue d'affichage du jeu (clé DisplayLanguage de UserOptions.txt)."""
    try:
        for line in (app_data / "UserOptions.txt").read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] == "DisplayLanguage":
                return parts[1]
    except OSError:
        pass
    return default


@dataclass(frozen=True)
class EngineConfig:
    lua_log: Path
    gameplay_db: Path
    localization_db: Path
    language: str
    game_dir: Path | None  # installation du jeu, pour les traductions des DLC (None : ignorées)
    data_dir: Path
    ws_host: str
    ws_port: int
    poll_interval_s: float

    @classmethod
    def from_env(cls) -> EngineConfig:
        app_data = civ6_app_data_dir()
        return cls(
            lua_log=Path(os.environ.get("CIVOVL_LUA_LOG", app_data / "Logs" / "Lua.log")),
            gameplay_db=Path(os.environ.get("CIVOVL_GAMEPLAY_DB", app_data / "Cache" / "DebugGameplay.sqlite")),
            localization_db=Path(
                os.environ.get("CIVOVL_LOCALIZATION_DB", app_data / "Cache" / "DebugLocalization.sqlite")
            ),
            language=os.environ.get("CIVOVL_LANGUAGE") or game_language(app_data),
            game_dir=Path(os.environ["CIVOVL_GAME_DIR"]) if os.environ.get("CIVOVL_GAME_DIR") else civ6_install_dir(),
            data_dir=Path(os.environ.get("CIVOVL_DATA_DIR", PROJECT_ROOT / "data")),
            ws_host="127.0.0.1",
            ws_port=int(os.environ.get("CIVOVL_WS_PORT", "8765")),
            poll_interval_s=float(os.environ.get("CIVOVL_POLL_INTERVAL", "0.25")),
        )
