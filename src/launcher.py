"""Lanceur : démarre le service moteur et l'overlay, sans console (spec 00 §3.1)."""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from ctypes import wintypes
from pathlib import Path
from typing import IO

log = logging.getLogger("launcher")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TITLE = "Civ VI Smart Overlay"
MUTEX_NAME = "Local\\CivVISmartOverlay.Launcher"

_ERROR_ALREADY_EXISTS = 183
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_MB_ICONERROR = 0x10
_MB_ICONINFORMATION = 0x40

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
_kernel32.CreateJobObjectW.restype = wintypes.HANDLE
_kernel32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
_kernel32.SetInformationJobObject.restype = wintypes.BOOL
_kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
_kernel32.AssignProcessToJobObject.restype = wintypes.BOOL


class _JobBasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JobExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobBasicLimits),
        ("IoInfo", ctypes.c_ulonglong * 6),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def acquire_single_instance(name: str = MUTEX_NAME) -> int | None:
    """Handle du mutex (à garder ouvert), ou None si une autre instance le détient."""
    handle = _kernel32.CreateMutexW(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(wintypes.HANDLE(handle))
        return None
    return handle


def create_kill_on_close_job() -> int | None:
    """Job dont les processus sont tués à sa fermeture, donc aussi si le lanceur est tué."""
    job = _kernel32.CreateJobObjectW(None, None)
    limits = _JobExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not job or not _kernel32.SetInformationJobObject(
        job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits)
    ):
        log.warning("Job Windows indisponible : %s", ctypes.WinError(ctypes.get_last_error()))
        return None
    return job


def _start(command: Sequence[str], log_file: IO[bytes], job: int | None) -> subprocess.Popen[bytes]:
    # UTF-8 forcé : sinon les logs en français suivraient la page de code du système.
    process = subprocess.Popen(
        command, cwd=PROJECT_ROOT, env={**os.environ, "PYTHONUTF8": "1"},
        stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT,
    )
    if job is not None and not _kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle))):
        log.warning("Processus %d hors du job : %s", process.pid, ctypes.WinError(ctypes.get_last_error()))
    return process


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        log.warning("Le service s'est arrêté avant l'overlay (code %d)", process.returncode)
        return
    process.terminate()
    process.wait()


def run(
    service_command: Sequence[str], overlay_command: Sequence[str], log_dir: Path, notify: Callable[[str, int], None]
) -> int:
    """Lance les deux processus et attend la fin de l'overlay ; retourne son code de sortie."""
    job = create_kill_on_close_job()
    with open(log_dir / "service.log", "wb") as service_log, open(log_dir / "overlay.log", "wb") as overlay_log:
        service = _start(service_command, service_log, job)
        log.info("Service démarré (processus %d)", service.pid)
        try:
            overlay = _start(overlay_command, overlay_log, job)
            log.info("Overlay démarré (processus %d)", overlay.pid)
            code = overlay.wait()
        finally:
            _stop(service)
    log.info("Overlay terminé (code %d)", code)
    if code != 0:
        notify(f"L'overlay s'est arrêté sur une erreur (code {code}).\nLogs : {log_dir}", _MB_ICONERROR)
    return code


def _message_box(text: str, icon: int) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, TITLE, icon)


def main() -> int:
    log_dir = Path(os.environ.get("CIVOVL_DATA_DIR", PROJECT_ROOT / "data")) / "logs"
    mutex = acquire_single_instance()
    if mutex is None:
        _message_box(
            "L'overlay est déjà lancé.\nCtrl+Alt+H l'affiche ; Ctrl+Alt+O puis « × » le ferme.", _MB_ICONINFORMATION
        )
        return 0
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=log_dir / "launcher.log", filemode="w", encoding="utf-8", level=logging.INFO,
            format="%(asctime)s %(levelname)-7s %(name)s : %(message)s",
        )
        python = sys.executable
        return run(
            [python, str(PROJECT_ROOT / "src" / "engine" / "service.py")],
            [python, str(PROJECT_ROOT / "src" / "ui" / "main.py")],
            log_dir, _message_box,
        )
    except OSError as exc:
        log.exception("Lancement impossible")
        _message_box(f"Lancement impossible : {exc}\nLogs : {log_dir}", _MB_ICONERROR)
        return 1


if __name__ == "__main__":
    sys.exit(main())
