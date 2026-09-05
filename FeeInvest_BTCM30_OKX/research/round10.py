"""Round 10 — (a) fair percent-distance re-test of every earlier family
over 4.3 years (bar: every year >= 60%, overall >= 70%), (b) hunt for a
second, mechanism-uncorrelated momentum/trend strategy.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.lab import (
    Candle, Trade, load_candles, ema_series, sma_std, atr_simple, stoch_k,
)
from research.round7 import run_bt_pct
from research.round8 import families
from research.round9 import _wr, by_year_line, year_of


def eval_family(candles, name, sigs, pcts=(1.5, 2.0, 2.5)):
    lines = []
    for pct in pcts:
        trades = run_bt_pct(candles, sigs, pct)
        if not trades:
            continue
        by_y: Dict[int, List[Trade]] = {}
        for t in trades:
            by_y.setdefault(year_of(candles, t), []).append(t)
        yr_wr = {y: sum(x.win for x in ts) / len(ts) * 100 for y, ts in by_y.items()}
        n = len(trades)
        w = sum(t.win for t in trades)
        ok = (w / n * 100 >= 70.0) and all(v >= 60.0 for v in yr_wr.values()) and n >= 30
        lines.append((ok, f"  [{'PASS' if ok else 'fail'}] {name:22s} pct{pct:.1f}: "
                          f"ALL {_wr(trades)} | {by_year_line(candles, trades)}"))
    return lines


def part_a(candles):
    print("=" * 78)
    print("A) PERCENT-DISTANCE RE-TEST of all families (4.3y; every year >=60%, ALL >=70%)")
    print("=" * 78)
    passes = []
    for name, sigs in families(candles).items():
        for ok, line in eval_family(candles, name, sigs):
            if ok:
                print(line)
                passes.append(line)
            elif "flagship" in name or "tight" in name:
                print(line)      # always show the known champions for reference
    if not passes:
        print("  (no additional family passes)")


def part_b(candles):
    print()
    print("=" * 78)
    print("B) MOMENTUM / TREND HUNT (mechanism-uncorrelated second strategy)")
    print("=" * 78)
    closes = [c.close for c in candles]
    vols = [c.volume for c in candles]
    n = len(candles)
    atr = atr_simple(candles, 14)
    ema20 = ema_series(closes, 20)
    ema50 = ema_series(closes, 50)
    vmean20, _ = sma_std(vols, 20)
    out: Dict[str, List[Tuple[int, int]]] = {}

    # strong-close continuation: big bar closing at its extreme -> follow
    for mult in (2.0, 2.5):
        sigs = []
        for i, c in enumerate(candles):
            rng = c.high - c.low
            if rng <= 0 or atr[i] != atr[i] or rng <= mult * atr[i]:
                continue
            pos = (c.close - c.low) / rng
            if pos > 0.9:
                sigs.append((i, 1))
            elif pos < 0.1:
                sigs.append((i, -1))
        out[f"strongclose_{mult}x"] = sigs

    # N-bar momentum burst: move over 12 bars > k*ATR -> follow
    for k in (3.0, 5.0):
        sigs = []
        for i in range(12, n):
            if atr[i] != atr[i]:
                continue
            mv = closes[i] - closes[i - 12]
            if mv > k * atr[i]:
                sigs.append((i, 1))
            elif mv < -k * atr[i]:
                sigs.append((i, -1))
        out[f"mom12_{k}atr"] = sigs

    # trend + pullback: EMA50 rising and close dips under EMA20 -> long (mirror short)
    sigs = []
    for i in range(60, n):
        if ema50[i] != ema50[i] or ema20[i] != ema20[i]:
            continue
        rising = ema50[i] > ema50[i - 10]
        if rising and closes[i] < ema20[i]:
            sigs.append((i, 1))
        elif not rising and closes[i] > ema20[i]:
            sigs.append((i, -1))
    out["trend_pullback"] = sigs

    # 50-bar close breakout with volume push
    sigs = []
    for i in range(51, n):
        if vmean20[i] != vmean20[i]:
            continue
        hi = max(closes[i - 50:i])
        lo = min(closes[i - 50:i])
        if closes[i] > hi and vols[i] > 1.5 * vmean20[i]:
            sigs.append((i, 1))
        elif closes[i] < lo and vols[i] > 1.5 * vmean20[i]:
            sigs.append((i, -1))
    out["break50_vol"] = sigs

    # 3-bar thrust: three expanding closes same direction -> follow
    sigs = []
    for i in range(3, n):
        b = [closes[j] - candles[j].open for j in range(i - 2, i + 1)]
        if all(x > 0 for x in b) and b[2] > b[1] > b[0]:
            sigs.append((i, 1))
        elif all(x < 0 for x in b) and b[2] < b[1] < b[0]:
            sigs.append((i, -1))
    out["thrust3"] = sigs

    for name, s in out.items():
        for ok, line in eval_family(candles, name, s):
            print(line)


if __name__ == "__main__":
    c30 = load_candles("30m")
    part_a(c30)
    part_b(c30)
