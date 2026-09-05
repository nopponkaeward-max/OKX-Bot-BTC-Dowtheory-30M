"""Round 2 — refine the round-1 winners (30m mean-reversion cluster).

Adds: trend filter (EMA200), one-sided variants, multi-signal confluence,
volume-spike fade, MACD cross, Williams %R, and larger distances.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.lab import (
    Candle, Result, run_bt, load_candles, leaderboard, MIN_TRADES,
    rsi_series, ema_series, sma_std, atr_simple, stoch_k,
)

DISTS = [1000.0, 1500.0, 2000.0, 2500.0, 3000.0]
TFS = ["15m", "30m", "1H", "2H"]


def gen(candles: List[Candle]) -> Dict[str, List[Tuple[int, int]]]:
    closes = [c.close for c in candles]
    vols = [c.volume for c in candles]
    n = len(candles)
    atr = atr_simple(candles, 14)
    ema200 = ema_series(closes, 200)
    k14 = stoch_k(candles, 14)
    mean20, std20 = sma_std(closes, 20)
    vmean20, _ = sma_std(vols, 20)
    r14 = rsi_series(closes, 14)
    out: Dict[str, List[Tuple[int, int]]] = {}

    def trend_up(i):  # price above EMA200
        return ema200[i] == ema200[i] and closes[i] > ema200[i]

    def trend_dn(i):
        return ema200[i] == ema200[i] and closes[i] < ema200[i]

    # --- base signals from round-1 winners ---
    stoch_sig = [(i, 1 if k14[i] < 10 else -1) for i in range(n)
                 if k14[i] == k14[i] and (k14[i] < 10 or k14[i] > 90)]
    boll_sig = []
    for i in range(n):
        if mean20[i] == mean20[i]:
            if closes[i] < mean20[i] - 2.0 * std20[i]:
                boll_sig.append((i, 1))
            elif closes[i] > mean20[i] + 2.0 * std20[i]:
                boll_sig.append((i, -1))
    fade_sig = [(i, 1 if closes[i] < candles[i].open else -1) for i in range(n)
                if atr[i] == atr[i] and (candles[i].high - candles[i].low) > 2.5 * atr[i]]

    for tag, base in (("stoch10/90", stoch_sig), ("boll2.0", boll_sig), ("fade2.5", fade_sig)):
        out[f"{tag}"] = base
        out[f"{tag}_L"] = [(i, d) for i, d in base if d > 0]
        out[f"{tag}_S"] = [(i, d) for i, d in base if d < 0]
        # fade only against stretch, WITH the higher trend (buy dips in uptrend)
        out[f"{tag}_wtrend"] = [(i, d) for i, d in base
                                if (d > 0 and trend_up(i)) or (d < 0 and trend_dn(i))]
        out[f"{tag}_ctrend"] = [(i, d) for i, d in base
                                if (d > 0 and trend_dn(i)) or (d < 0 and trend_up(i))]

    # --- confluence: stoch extreme AND bollinger breach ---
    bset = {(i, d) for i, d in boll_sig}
    out["confl_stoch+boll"] = [(i, d) for i, d in stoch_sig if (i, d) in bset]
    fset = {(i, d) for i, d in fade_sig}
    out["confl_fade+boll"] = [(i, d) for i, d in fade_sig if (i, d) in bset]
    out["confl_stoch+fade"] = [(i, d) for i, d in stoch_sig if (i, d) in fset]

    # --- RSI14 + stoch double oversold ---
    out["confl_rsi30+stoch10"] = [
        (i, 1) for i in range(n)
        if r14[i] == r14[i] and k14[i] == k14[i] and r14[i] < 30 and k14[i] < 10
    ] + [
        (i, -1) for i in range(n)
        if r14[i] == r14[i] and k14[i] == k14[i] and r14[i] > 70 and k14[i] > 90
    ]

    # --- volume-spike fade: volume > 3x avg + directional close -> fade ---
    for vm in (3.0, 4.0):
        sigs = []
        for i in range(n):
            if vmean20[i] == vmean20[i] and vols[i] > vm * vmean20[i]:
                sigs.append((i, 1 if closes[i] < candles[i].open else -1))
        out[f"volspike_fade_{vm}x"] = sigs

    # --- MACD signal-line cross ---
    e12, e26 = ema_series(closes, 12), ema_series(closes, 26)
    macd = [a - b if a == a and b == b else float("nan") for a, b in zip(e12, e26)]
    sigl = ema_series([m if m == m else 0.0 for m in macd], 9)
    sigs = []
    for i in range(27, n):
        if macd[i] == macd[i] and macd[i - 1] == macd[i - 1]:
            if macd[i - 1] <= sigl[i - 1] and macd[i] > sigl[i]:
                sigs.append((i, 1))
            elif macd[i - 1] >= sigl[i - 1] and macd[i] < sigl[i]:
                sigs.append((i, -1))
    out["macd_cross"] = sigs

    # --- Williams %R style: close in lowest 5% of 50-bar range ---
    for look in (50, 100):
        sigs = []
        for i in range(look, n):
            hi = max(c.high for c in candles[i - look + 1:i + 1])
            lo = min(c.low for c in candles[i - look + 1:i + 1])
            if hi == lo:
                continue
            pos = (closes[i] - lo) / (hi - lo)
            if pos < 0.05:
                sigs.append((i, 1))
            elif pos > 0.95:
                sigs.append((i, -1))
        out[f"range{look}_edge_rev"] = sigs

    return out


def main():
    results: List[Result] = []
    for tf in TFS:
        candles = load_candles(tf)
        sigs = gen(candles)
        for name, s in sigs.items():
            for dist in DISTS:
                results.append(Result(name=name, tf=tf, dist=dist,
                                      trades=run_bt(candles, s, dist)))
        print(f"{tf}: {len(sigs)} strategies done")
    print()
    print(leaderboard(results, top=30))
    hits = [r for r in results if r.n >= MIN_TRADES and r.winrate >= 70.0]
    print(f"\n>=70% winrate candidates (>= {MIN_TRADES} trades): {len(hits)}")
    for r in hits:
        print(f"  {r.name} {r.tf} dist={r.dist:.0f} trades={r.n} win%={r.winrate:.1f} netR={r.net_r:+.0f}")


if __name__ == "__main__":
    main()
