"""Robustness checks for a candidate strategy: period split, monthly and
side breakdown.  Usage: python -m research.validate
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.lab import Candle, run_bt, load_candles, atr_simple, stoch_k


def confl_stoch_fade(candles: List[Candle]) -> List[Tuple[int, int]]:
    """Stoch %K extreme (<10 / >90) AND bar range > 2.5*ATR(14) -> fade the bar."""
    closes = [c.close for c in candles]
    atr = atr_simple(candles, 14)
    k14 = stoch_k(candles, 14)
    sigs = []
    for i, c in enumerate(candles):
        if atr[i] != atr[i] or k14[i] != k14[i]:
            continue
        big = (c.high - c.low) > 2.5 * atr[i]
        if not big:
            continue
        fade_dir = 1 if closes[i] < c.open else -1
        stoch_ok = (k14[i] < 10 and fade_dir > 0) or (k14[i] > 90 and fade_dir < 0)
        if stoch_ok:
            sigs.append((i, fade_dir))
    return sigs


def month_of(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m")


def report(tf: str, dist: float):
    candles = load_candles(tf)
    sigs = confl_stoch_fade(candles)
    trades = run_bt(candles, sigs, dist)
    n = len(trades)
    if not n:
        print(f"{tf} d{dist:.0f}: no trades")
        return
    wins = sum(t.win for t in trades)
    half = n // 2
    h1, h2 = trades[:half], trades[half:]
    w1 = sum(t.win for t in h1) / len(h1) * 100 if h1 else 0
    w2 = sum(t.win for t in h2) / len(h2) * 100 if h2 else 0
    longs = [t for t in trades if t.dir > 0]
    shorts = [t for t in trades if t.dir < 0]
    wl = sum(t.win for t in longs) / len(longs) * 100 if longs else 0
    ws = sum(t.win for t in shorts) / len(shorts) * 100 if shorts else 0
    # avg holding bars
    hold = sum(t.close_bar - t.entry_bar for t in trades) / n
    print(f"\n=== {tf} dist={dist:.0f} | {n} trades, win {wins/n*100:.1f}%, "
          f"netR {wins - (n - wins):+d}, avg hold {hold:.1f} bars ===")
    print(f"  1st half: {len(h1)}t {w1:.1f}%   2nd half: {len(h2)}t {w2:.1f}%")
    print(f"  LONG: {len(longs)}t {wl:.1f}%   SHORT: {len(shorts)}t {ws:.1f}%")
    by_m: Dict[str, List[bool]] = {}
    for t in trades:
        by_m.setdefault(month_of(candles[t.entry_bar].ts), []).append(t.win)
    row = "  monthly: "
    for m in sorted(by_m):
        ws_ = by_m[m]
        row += f"{m[2:]}:{sum(ws_)}/{len(ws_)} "
    print(row)


def main():
    for tf, dists in (("30m", (1500, 2000, 2500, 3000)), ("1H", (1500, 2000))):
        for d in dists:
            report(tf, float(d))


if __name__ == "__main__":
    main()
