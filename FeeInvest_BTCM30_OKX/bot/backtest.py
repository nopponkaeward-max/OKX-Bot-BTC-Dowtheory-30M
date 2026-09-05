"""Backtest the strategy over historical candles.

Runs the pure engine with ``simulate_fills=True`` — the exact win/loss logic
of the indicator — and prints the reproduced statistics.
"""

from __future__ import annotations

from typing import List, Optional

from .config import Config
from .engine import Candle, LtfProviderT, StrategyEngine
from . import stats


def run_backtest(cfg: Config, candles: List[Candle], verbose: bool = False,
                 ltf_provider: Optional[LtfProviderT] = None) -> StrategyEngine:
    eng = StrategyEngine(cfg, simulate_fills=True, ltf_provider=ltf_provider)
    for c in candles:
        eng.process_candle(c)
    if verbose:
        for t in eng.closed_trades:
            side = "BUY " if t.is_buy else "SELL"
            typ = "Mid" if t.ptype == 1 else "PB "
            res = "WIN " if t.is_win else "LOSS"
            print(f"{typ} {side} {res} R={t.r:+.2f} entry={t.entry:.1f} sl={t.sl:.1f} tp={t.tp:.1f}")
    return eng


def summary(eng: StrategyEngine, tz_offset: int = 0, months: int = 8) -> str:
    return stats.render(eng.closed_trades, tz_offset=tz_offset, months=months)
