"""Backtest the Session Breakout strategy over historical candles."""

from __future__ import annotations

from typing import List

from .config import Config
from .engine import Candle, StrategyEngine
from . import stats


def run_backtest(cfg: Config, candles: List[Candle],
                 verbose: bool = False) -> StrategyEngine:
    eng = StrategyEngine(cfg)
    for c in candles:
        eng.on_bar(c)
    if verbose:
        for t in eng.closed:
            side = "BUY " if t.is_buy else "SELL"
            tag = "Order-3" if t.is_2nd and not t.is_addon else ("Order-2" if t.is_addon else "Order-1")
            res = "WIN " if t.is_win else "LOSS"
            reas = f" [{t.close_reason}]" if t.close_reason != "tp_sl" else ""
            print(f"{tag} {side} {res} R={t.r:+.2f} "
                  f"entry={t.entry:.1f} sl={t.sl:.1f} tp={t.tp:.1f}{reas}")
    return eng


def summary(eng: StrategyEngine, tz_offset: int = 0,
            months: int = 8) -> str:
    return stats.render(eng.closed, tz_offset=tz_offset, months=months)
