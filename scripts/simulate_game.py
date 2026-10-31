"""Simule une partie en écrivant des messages [CIVOVL] dans un faux Lua.log.

Permet de tester le service moteur et l'overlay sans lancer Civ VI :

    python scripts/simulate_game.py data/fake_Lua.log
    $env:CIVOVL_LUA_LOG = "data/fake_Lua.log"; python src/engine/service.py
    python src/ui/main.py
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

CHUNK_SIZE = 900


def write_message(path: Path, msg_id: int, state: dict) -> None:
    payload = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    chunks = [payload[i:i + CHUNK_SIZE] for i in range(0, len(payload), CHUNK_SIZE)]
    with path.open("ab") as f:
        for part, chunk in enumerate(chunks, start=1):
            f.write(b"GameStateExporter: [CIVOVL] %d %d/%d " % (msg_id, part, len(chunks)) + chunk + b"\n")


def build_state(turn: int, trigger: str) -> dict:
    return {
        "schema_version": 1,
        "meta": {"trigger": trigger, "extraction_ms": 2},
        "game": {"turn": turn},
        "player": {"player_id": 0, "civilization": "CIVILIZATION_ROME", "leader": "LEADER_TRAJAN"},
        "yields": {
            "gold": 10.0 + turn * 6.5,
            "gold_per_turn": 3.0 + turn * 0.4,
            "science_per_turn": 2.5 + turn * 0.6,
            "culture_per_turn": 1.5 + turn * 0.5,
            "faith": turn * 1.5,
            "faith_per_turn": 1.0 + turn * 0.1,
        },
        "techs": {"current_research": "TECH_POTTERY" if turn < 6 else "TECH_HORSEBACK_RIDING"},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log_path", type=Path)
    parser.add_argument("--turns", type=int, default=30)
    parser.add_argument("--interval", type=float, default=3.0, help="secondes entre deux tours")
    args = parser.parse_args()

    args.log_path.parent.mkdir(parents=True, exist_ok=True)
    args.log_path.write_bytes(b"")  # comme le jeu au lancement
    msg_id = 0
    for turn in range(1, args.turns + 1):
        for trigger in ("turn_begin", "turn_end"):
            msg_id += 1
            write_message(args.log_path, msg_id, build_state(turn, trigger))
            print(f"Tour {turn} : {trigger}")
            time.sleep(args.interval / 2)


if __name__ == "__main__":
    main()
