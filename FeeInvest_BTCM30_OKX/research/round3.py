"""Round 3 — (a) out-of-sample test of confl_stoch+fade on unseen Jun–Dec
2025 30m data, (b) parameter-neighborhood map (plateau check), (c) new
families: Keltner touch, ATR-stretch reversion, sweep-and-reclaim,
session-filtered variants.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.lab import (
    Candle, Result, run_bt, load_candles, leaderboard, MIN_TRADES,
    ema_series, atr_simple, stoch_k,
)
from research.validate import confl_stoch_fade

OOS_SPLIT_MS = 1_764_980_000_000  # ~2025-12-06 (start of the round-1/2 window)


def confl_variant(candles: List[Candle], stoch_lo: float, stoch_hi: float,
                  atr_mult: float, stoch_p: int = 14) -> List[Tuple[int, int]]:
    closes = [c.close for c in candles]
    atr = atr_simple(candles, 14)
    k = stoch_k(candles, stoch_p)
    sigs = []
    for i, c in enumerate(candles):
        if atr[i] != atr[i] or k[i] != k[i]:
            continue
        if (c.high - c.low) <= atr_mult * atr[i]:
            continue
        d = 1 if closes[i] < c.open else -1
        if (k[i] < stoch_lo and d > 0) or (k[i] > stoch_hi and d < 0):
            sigs.append((i, d))
    return sigs


def _wr(trades) -> str:
    n = len(trades)
    if not n:
        return "0t"
    w = sum(t.win for t in trades)
    return f"{n}t {w / n * 100:.1f}% netR{w - (n - w):+d}"


def oos_test():
    print("=" * 70)
    print("A) OUT-OF-SAMPLE: confl_stoch+fade on 30m Jun-Dec 2025 (unseen data)")
    print("=" * 70)
    candles = load_candles("30m")
    pre = [c for c in candles if c.ts < OOS_SPLIT_MS]
    print(f"OOS window: {len(pre)} bars "
          f"({datetime.fromtimestamp(pre[0].ts/1000, tz=timezone.utc):%Y-%m-%d} .. "
          f"{datetime.fromtimestamp(pre[-1].ts/1000, tz=timezone.utc):%Y-%m-%d})")
    sigs = confl_stoch_fade(pre)
    for dist in (1500.0, 2000.0, 2500.0, 3000.0):
        print(f"  dist {dist:>5.0f}: OOS {_wr(run_bt(pre, sigs, dist))}")
    full_sigs = confl_stoch_fade(candles)
    print("Full 15-month window:")
    for dist in (1500.0, 2000.0, 2500.0, 3000.0):
        print(f"  dist {dist:>5.0f}: FULL {_wr(run_bt(candles, full_sigs, dist))}")


def plateau_map():
    print()
    print("=" * 70)
    print("B) PARAMETER NEIGHBORHOOD (30m, full 15 months, dist=2500)")
    print("=" * 70)
    candles = load_candles("30m")
    for lo, hi in ((5, 95), (10, 90), (15, 85), (20, 80)):
        for mult in (2.0, 2.5, 3.0):
            sigs = confl_variant(candles, lo, hi, mult)
            print(f"  stoch<{lo:>2}/>{hi:<2} atr>{mult}x : {_wr(run_bt(candles, sigs, 2500.0))}")


def new_families():
    print()
    print("=" * 70)
    print("C) NEW FAMILIES (30m + 1H)")
    print("=" * 70)
    results: List[Result] = []
    for tf in ("30m", "1H"):
        candles = load_candles(tf)
        closes = [c.close for c in candles]
        n = len(candles)
        atr = atr_simple(candles, 14)
        ema20 = ema_series(closes, 20)
        out: Dict[str, List[Tuple[int, int]]] = {}

        # Keltner touch reversion: close beyond EMA20 +/- k*ATR
        for k in (2.0, 3.0):
            sigs = []
            for i in range(n):
                if ema20[i] != ema20[i] or atr[i] != atr[i]:
                    continue
                if closes[i] < ema20[i] - k * atr[i]:
                    sigs.append((i, 1))
                elif closes[i] > ema20[i] + k * atr[i]:
                    sigs.append((i, -1))
            out[f"keltner_rev_k{k}"] = sigs

        # ATR-stretch: distance from EMA20 in ATR units
        for z in (2.5, 3.5):
            sigs = []
            for i in range(n):
                if ema20[i] != ema20[i] or atr[i] != atr[i] or atr[i] == 0:
                    continue
                st = (closes[i] - ema20[i]) / atr[i]
                if st < -z:
                    sigs.append((i, 1))
                elif st > z:
                    sigs.append((i, -1))
            out[f"atrstretch_z{z}"] = sigs

        # Sweep-and-reclaim: take out an N-bar extreme intrabar, close back inside
        for look in (20, 50):
            sigs = []
            for i in range(look + 1, n):
                lo_prev = min(c.low for c in candles[i - look:i])
                hi_prev = max(c.high for c in candles[i - look:i])
                if candles[i].low < lo_prev and closes[i] > lo_prev:
                    sigs.append((i, 1))
                elif candles[i].high > hi_prev and closes[i] < hi_prev:
                    sigs.append((i, -1))
            out[f"sweep{look}_reclaim"] = sigs

        # Session-filtered stoch+fade (UTC 8h blocks)
        base = confl_stoch_fade(candles)
        for name, h0, h1 in (("asia", 0, 8), ("eu", 8, 16), ("us", 16, 24)):
            out[f"stochfade_{name}"] = [
                (i, d) for i, d in base
                if h0 <= datetime.fromtimestamp(candles[i].ts / 1000, tz=timezone.utc).hour < h1]

        for name, s in out.items():
            for dist in (1000.0, 1500.0, 2000.0, 2500.0, 3000.0):
                results.append(Result(name=name, tf=tf, dist=dist,
                                      trades=run_bt(candles, s, dist)))
    print(leaderboard(results, top=22))
    hits = [r for r in results if r.n >= MIN_TRADES and r.winrate >= 70.0]
    print(f"\n>=70% candidates: {len(hits)}")
    for r in hits:
        print(f"  {r.name} {r.tf} d{r.dist:.0f}: {r.n}t {r.winrate:.1f}% netR{r.net_r:+.0f}")


if __name__ == "__main__":
    oos_test()
    plateau_map()
    new_families()
