from __future__ import annotations

import json
from pathlib import Path

from conftest import to_log_lines
from engine.log_tailer import FragmentAssembler, LuaLogTailer


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def feed_all(assembler: FragmentAssembler, lines: list[bytes]) -> list[bytes]:
    return [m for line in lines if (m := assembler.feed_line(line)) is not None]


def test_single_fragment_message(mvp0_payload: bytes) -> None:
    assembler = FragmentAssembler()
    assert feed_all(assembler, to_log_lines(mvp0_payload, msg_id=1)) == [mvp0_payload]


def test_multi_fragment_message_with_noise(mvp0_payload: bytes) -> None:
    lines = to_log_lines(mvp0_payload, msg_id=7, chunk_size=50)
    assert len(lines) > 3
    noisy = [b"InGame: Loading...", *lines[:2], b"TopPanel: unrelated", *lines[2:]]
    assert feed_all(FragmentAssembler(), noisy) == [mvp0_payload]


def test_out_of_order_fragments(mvp0_payload: bytes) -> None:
    lines = to_log_lines(mvp0_payload, msg_id=3, chunk_size=50)
    assert feed_all(FragmentAssembler(), [lines[1], lines[0], *lines[2:]]) == [mvp0_payload]


def test_utf8_character_split_across_fragments() -> None:
    payload = json.dumps({"name": "Évreux-Côté"}, ensure_ascii=False).encode("utf-8")
    split_at = payload.index("É".encode("utf-8")) + 1  # au milieu du caractère
    lines = to_log_lines(payload, msg_id=1, chunk_size=split_at)
    result = feed_all(FragmentAssembler(), lines)
    assert [r.decode("utf-8") for r in result] == [payload.decode("utf-8")]


def test_crlf_line_endings(mvp0_payload: bytes) -> None:
    lines = [line + b"\r" for line in to_log_lines(mvp0_payload, msg_id=1, chunk_size=60)]
    assert feed_all(FragmentAssembler(), lines) == [mvp0_payload]


def test_incomplete_message_dropped_when_new_id_arrives(mvp0_payload: bytes) -> None:
    first = to_log_lines(mvp0_payload, msg_id=1, chunk_size=50)
    second = to_log_lines(mvp0_payload, msg_id=2, chunk_size=50)
    assert feed_all(FragmentAssembler(), [first[0], *second]) == [mvp0_payload]


def test_reused_msg_id_after_mod_reload(mvp0_payload: bytes) -> None:
    # Même msg_id et même nombre de fragments : seul le fragment 1 en double révèle le rechargement.
    stale = to_log_lines(b"x" * len(mvp0_payload), msg_id=1, chunk_size=50)
    fresh = to_log_lines(mvp0_payload, msg_id=1, chunk_size=50)
    assert feed_all(FragmentAssembler(), [stale[0], *fresh]) == [mvp0_payload]


def test_incomplete_message_dropped_after_timeout(mvp0_payload: bytes) -> None:
    clock = FakeClock()
    assembler = FragmentAssembler(timeout_s=10.0, clock=clock)
    lines = to_log_lines(mvp0_payload, msg_id=1, chunk_size=50)
    assert assembler.feed_line(lines[0]) is None
    clock.now = 11.0
    assert feed_all(assembler, lines[1:]) == []


def test_invalid_part_numbers_ignored() -> None:
    assembler = FragmentAssembler()
    assert assembler.feed_line(b"[CIVOVL] 1 3/2 {}") is None
    assert assembler.feed_line(b"[CIVOVL] 1 0/1 {}") is None


def append(path: Path, lines: list[bytes], terminate: bool = True) -> None:
    with path.open("ab") as f:
        f.write(b"\n".join(lines) + (b"\n" if terminate else b""))


def test_tailer_waits_for_missing_file(tmp_path: Path) -> None:
    assert LuaLogTailer(tmp_path / "Lua.log").poll() == []


def test_tailer_reads_incrementally(tmp_path: Path, mvp0_payload: bytes) -> None:
    log_path = tmp_path / "Lua.log"
    tailer = LuaLogTailer(log_path)
    lines = to_log_lines(mvp0_payload, msg_id=1, chunk_size=60)

    append(log_path, lines[:2])
    assert tailer.poll() == []
    append(log_path, lines[2:])
    assert tailer.poll() == [mvp0_payload]
    assert tailer.poll() == []


def test_tailer_handles_partial_last_line(tmp_path: Path, mvp0_payload: bytes) -> None:
    log_path = tmp_path / "Lua.log"
    tailer = LuaLogTailer(log_path)
    (line,) = to_log_lines(mvp0_payload, msg_id=1)

    with log_path.open("ab") as f:
        f.write(line[:30])
    assert tailer.poll() == []
    with log_path.open("ab") as f:
        f.write(line[30:] + b"\n")
    assert tailer.poll() == [mvp0_payload]


def test_tailer_restarts_when_file_truncated(tmp_path: Path, mvp0_payload: bytes) -> None:
    log_path = tmp_path / "Lua.log"
    tailer = LuaLogTailer(log_path)
    append(log_path, [b"x" * 5000])
    assert tailer.poll() == []

    log_path.write_bytes(b"")  # le jeu recrée Lua.log au lancement
    append(log_path, to_log_lines(mvp0_payload, msg_id=1))
    assert tailer.poll() == [mvp0_payload]
