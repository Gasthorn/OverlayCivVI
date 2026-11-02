"""Lanceur : instance unique et durée de vie des processus (spec 00 §3.1)."""

from __future__ import annotations

import subprocess
import sys
import time
import uuid
from pathlib import Path

import launcher

# Écrit son PID dans un fichier, puis attend d'être arrêté.
SLEEPER = "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(60)"


def _is_running(pid: int) -> bool:
    output = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=True
    ).stdout
    return f'"{pid}"' in output


def _wait_for(predicate, timeout_s: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_second_instance_is_refused() -> None:
    name = f"Local\\CivVISmartOverlay.Test.{uuid.uuid4()}"
    assert launcher.acquire_single_instance(name) is not None
    assert launcher.acquire_single_instance(name) is None


def test_service_is_stopped_when_overlay_exits(tmp_path: Path) -> None:
    pid_file = tmp_path / "service.pid"
    notifications: list[str] = []

    # L'overlay attend que le service ait écrit son PID, puis se ferme normalement.
    overlay = f"import pathlib, time\nwhile not pathlib.Path(r'{pid_file}').exists(): time.sleep(0.05)"
    code = launcher.run(
        [sys.executable, "-c", SLEEPER, str(pid_file)],
        [sys.executable, "-c", overlay],
        tmp_path, lambda text, icon: notifications.append(text),
    )

    assert code == 0
    assert notifications == []
    pid = int(pid_file.read_text())
    assert _wait_for(lambda: not _is_running(pid))


def test_overlay_error_is_reported_and_stops_service(tmp_path: Path) -> None:
    pid_file = tmp_path / "service.pid"
    notifications: list[str] = []

    overlay = f"import pathlib, time\nwhile not pathlib.Path(r'{pid_file}').exists(): time.sleep(0.05)\nraise SystemExit(3)"
    code = launcher.run(
        [sys.executable, "-c", SLEEPER, str(pid_file)],
        [sys.executable, "-c", overlay],
        tmp_path, lambda text, icon: notifications.append(text),
    )

    assert code == 3
    assert len(notifications) == 1 and str(tmp_path) in notifications[0]
    pid = int(pid_file.read_text())
    assert _wait_for(lambda: not _is_running(pid))


def test_children_die_with_the_launcher(tmp_path: Path) -> None:
    """Lanceur tué brutalement : le job Windows emporte le service et l'overlay."""
    service_pid, overlay_pid = tmp_path / "service.pid", tmp_path / "overlay.pid"
    script = (
        "import sys, launcher, pathlib\n"
        f"sys.exit(launcher.run([sys.executable, '-c', {SLEEPER!r}, r'{service_pid}'],"
        f" [sys.executable, '-c', {SLEEPER!r}, r'{overlay_pid}'], pathlib.Path(r'{tmp_path}'), print))"
    )
    src = Path(launcher.__file__).parent
    parent = subprocess.Popen([sys.executable, "-c", f"import sys; sys.path.insert(0, r'{src}')\n{script}"])
    try:
        assert _wait_for(lambda: service_pid.exists() and overlay_pid.exists()), "enfants non démarrés"
        assert _wait_for(lambda: service_pid.read_text() != "" and overlay_pid.read_text() != "")
        pids = int(service_pid.read_text()), int(overlay_pid.read_text())
        assert all(_is_running(pid) for pid in pids)
    finally:
        parent.kill()
    assert _wait_for(lambda: not any(_is_running(pid) for pid in pids))
