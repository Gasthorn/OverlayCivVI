"""Point d'entrée du service moteur : python src/engine/service.py (spec 02)."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.archive import Archive
from engine.city_layout import CityPlotsCache, city_layouts
from engine.config import EngineConfig
from engine.game_db import GameDbProvider
from engine.log_tailer import LuaLogTailer
from engine.preferences import FollowedStrategies
from engine.recommendations import RECOMPUTE_TRIGGERS, build_recommendations, build_status
from engine.rules import run_rules
from engine.session import GameSession
from engine.settling import settle_message
from engine.state import GameState, InvalidGameState, parse_game_state
from engine.strategies import STRATEGIES, score_strategies
from engine.ws_server import Broadcaster

log = logging.getLogger("engine")

STRATEGY_IDS = frozenset(s[0] for s in STRATEGIES)


class EngineService:
    def __init__(self, config: EngineConfig, broadcaster: Broadcaster) -> None:
        self.config = config
        self.broadcaster = broadcaster
        self.broadcaster.on_client_message = self.handle_client_message
        self.tailer = LuaLogTailer(config.lua_log)
        self.archive = Archive(config.data_dir, enabled=config.archive)
        self.session = GameSession()
        self.game_db = GameDbProvider(config.gameplay_db, config.localization_db, config.language, config.game_dir)
        self.followed = FollowedStrategies(config.data_dir)
        self.city_plots = CityPlotsCache()
        self._last_state: GameState | None = None
        self._last_game_id: str | None = None
        self._last_recommendations: dict[str, Any] | None = None

    # --- Entrées ------------------------------------------------------------------

    def handle_payload(self, payload: bytes) -> None:
        try:
            state = parse_game_state(payload)
        except InvalidGameState as exc:
            log.warning("game_state ignoré : %s", exc)
            return

        game_id = self.session.resolve_game_id(state)
        try:
            self.archive.save(game_id, state)
        except OSError as exc:
            log.error("Archivage impossible : %s", exc)

        self._last_state, self._last_game_id = state, game_id
        self._publish(state, game_id, recompute=False)

    def handle_client_message(self, message: dict[str, Any]) -> None:
        if message["type"] != "follow_strategy":
            return
        strategy_id = message["strategy_id"]
        if strategy_id is not None and strategy_id not in STRATEGY_IDS:
            log.warning("Stratégie inconnue ignorée : %s", strategy_id)
            return
        if self._last_game_id is None or self._last_state is None:
            log.info("Stratégie %s ignorée : aucune partie en cours", strategy_id)
            return
        self.followed.set(self._last_game_id, strategy_id)
        log.info("Stratégie suivie : %s", strategy_id or "aucune")
        self._publish(self._last_state, self._last_game_id, recompute=True)

    # --- Publication -----------------------------------------------------------------

    def _publish(self, state: GameState, game_id: str, recompute: bool) -> None:
        db = self.game_db.get()
        if self.game_db.error:
            status = build_status("degraded", turn=state.turn, game_id=game_id, detail=self.game_db.error)
        else:
            status = build_status("ok", turn=state.turn, game_id=game_id)
        self.broadcaster.publish(status)

        followed = self.followed.get(game_id)
        plots_by_city = self.city_plots.update(game_id, state, db)
        # Meilleurs emplacements recalculés depuis la carte (ressources protégées) ; hors début de
        # tour, le mod ne les exporte pas : on reprend les derniers connus.
        state = self.city_plots.enrich(state)
        actions = strategies = cities = settle = None
        if recompute or state.trigger in RECOMPUTE_TRIGGERS:
            if db is not None:
                actions = [a.to_message() for a in run_rules(state, db, followed_strategy=followed)]
                strategies = score_strategies(state, db)
                cities = city_layouts(state, db, plots_by_city, followed)
            settle = settle_message(state, db)

        log.info(
            "Tour %d (%s) pour %s : %d action(s), stratégie suivie : %s",
            state.turn, state.trigger, game_id, len(actions or []), followed or "aucune",
        )
        self._last_recommendations = build_recommendations(
            state, game_id, self._last_recommendations,
            actions=actions, strategies=strategies, cities=cities, settle=settle,
            followed_strategy=followed, recompute=recompute,
        )
        self.broadcaster.publish(self._last_recommendations)

    async def run(self) -> None:
        log.info("Lecture de %s", self.config.lua_log)
        self.broadcaster.publish(build_status("waiting_for_game"))
        while True:
            for payload in self.tailer.poll():
                self.handle_payload(payload)
            await asyncio.sleep(self.config.poll_interval_s)


async def main() -> None:
    config = EngineConfig.from_env()
    broadcaster = Broadcaster(config.ws_host, config.ws_port)
    await broadcaster.start()
    try:
        await EngineService(config, broadcaster).run()
    finally:
        await broadcaster.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s : %(message)s")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Arrêt du service")
