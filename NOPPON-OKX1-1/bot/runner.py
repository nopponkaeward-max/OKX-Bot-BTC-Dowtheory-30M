"""Live / dry-run runner loop for Session Breakout.

Warms the engine on recent closed candles (no orders placed for history),
then processes each newly closed bar:

* dry-run : engine simulates fills; intended orders and trades logged only.
* live    : executor places/cancels real OKX orders and tracks fills.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

from .config import Config
from .engine import Candle, StrategyEngine
from .okx_client import OKXClient
from .executor import Executor
from . import data as datamod
from . import stats

log = logging.getLogger("bot.runner")


def _setup_logging(cfg: Config):
    os.makedirs(os.path.dirname(cfg.runtime.log_file) or ".", exist_ok=True)
    handlers = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(cfg.runtime.log_file))
    except OSError:
        pass
    logging.basicConfig(
        level=getattr(logging, cfg.runtime.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


class Runner:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        _setup_logging(cfg)
        self.client = OKXClient(
            api_key=cfg.exchange.api_key, api_secret=cfg.exchange.api_secret,
            passphrase=cfg.exchange.passphrase, demo=cfg.exchange.demo,
            base_url=cfg.exchange.base_url)
        self.live = cfg.runtime.mode == "live"
        self.engine = StrategyEngine(cfg, live=self.live)
        self.executor: Optional[Executor] = (
            Executor(cfg, self.client) if self.live else None)
        self.last_ts: int = 0
        self._load_state()

    def _load_state(self):
        path = self.cfg.runtime.state_file
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if self.executor and "executor" in data:
                self.executor.load_state(data["executor"])
            if "engine" in data:
                self.engine.load_state(data["engine"])
            log.info("Loaded state from %s", path)
        except Exception as e:
            log.warning("Could not load state: %s", e)

    def _save_state(self):
        path = self.cfg.runtime.state_file
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        data = {"engine": self.engine.state_dict()}
        if self.executor:
            data["executor"] = self.executor.state_dict()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

    # ------------------------------------------------------------------
    def warmup(self):
        candles = datamod.fetch_recent(
            self.client, self.cfg.exchange.inst_id, self.cfg.exchange.bar,
            self.cfg.runtime.candle_history, only_confirmed=True)
        if not candles:
            log.error("No candles returned; aborting warmup")
            return
        log.info("Warmup on %d closed bars (%s %s)", len(candles),
                 self.cfg.exchange.inst_id, self.cfg.exchange.bar)
        for c in candles:
            events = self.engine.on_bar(c)
            if self.executor:
                self.executor.handle_events(events, act=False)
            self.last_ts = c.ts
        log.info("Warmup complete. Plans=%d Trades=%d",
                 len(self.engine.plans), len(self.engine.trades))

    # ------------------------------------------------------------------
    def step(self):
        if self.executor:
            self.executor.poll_fills()
        candles = datamod.fetch_recent(
            self.client, self.cfg.exchange.inst_id, self.cfg.exchange.bar,
            self.cfg.runtime.candle_history, only_confirmed=True)
        new = [c for c in candles if c.ts > self.last_ts]
        for c in new:
            events = self.engine.on_bar(c)
            if self.executor:
                self.executor.handle_events(events, act=True)
            else:
                self._log_dry(c)
            self.last_ts = c.ts

        if self.executor and new:
            self._save_state()

        if new:
            self._print_stats()

    def _log_dry(self, c: Candle):
        seen = getattr(self, "_dry_seen", 0)
        for t in self.engine.closed[seen:]:
            side = "BUY" if t.is_buy else "SELL"
            tag = "Order-3" if t.is_order3 and not t.is_order2 else ("Order-2" if t.is_order2 else "Order-1")
            res = "WIN" if t.is_win else "LOSS"
            log.info("[DRY] %s %s %s R=%+.2f entry=%.1f sl=%.1f tp=%.1f",
                     tag, side, res, t.r, t.entry, t.sl, t.tp)
        self._dry_seen = len(self.engine.closed)
        if self.engine.plans:
            log.info("[DRY] bar %s close=%.1f | plans=%d trades=%d",
                     c.ts, c.close, len(self.engine.plans),
                     len(self.engine.trades))

    def _print_stats(self):
        trades = (self.executor.closed if self.executor
                  else self.engine.closed)
        if trades:
            log.info("\n%s", stats.render(
                trades, tz_offset=self.cfg.strategy.tz_offset_hours))

    # ------------------------------------------------------------------
    def run(self):
        self.warmup()
        log.info("Entering %s loop (poll=%ss). Ctrl-C to stop.",
                 self.cfg.runtime.mode, self.cfg.runtime.poll_seconds)
        try:
            while True:
                try:
                    self.step()
                except Exception as e:
                    log.exception("step() error: %s", e)
                time.sleep(self.cfg.runtime.poll_seconds)
        except KeyboardInterrupt:
            log.info("Stopped by user.")
            self._save_state()
