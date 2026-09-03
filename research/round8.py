"""Round 8 — (a) survivor test: every earlier >=65% family re-run on the
full 2.7y with the stricter bar "every calendar year >= 60%",
(b) walk-forward regime gate on the flagship (trade only while the rolling
20-trade winrate >= threshold), (c) regime attribution: what switched the
edge on in mid-2025.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.lab import (
    Candle, Trade, run_bt, load_candles,
    rsi_series, ema_series, sma_std, atr_simple, stoch_k,
)
from research.validate import confl_stoch_fade
from research.round3 import confl_variant


def _wr(trades) -> str:
    n = len(trades)
    if not n:
        return "   0t"
    w = sum(t.win for t in trades)
    return f"{n:>4d}t {w / n * 100:5.1f}%"


def year_of(candles, t: Trade) -> int:
    return datetime.fromtimestamp(candles[t.entry_bar].ts / 1000, tz=timezone.utc).year


# ------------------------------------------------------------------
def families(candles: List[Candle]) -> Dict[str, List[Tuple[int, int]]]:
    closes = [c.close for c in candles]
    n = len(candles)
    atr = atr_simple(candles, 14)
    k14 = stoch_k(candles, 14)
    mean20, std20 = sma_std(closes, 20)
    ema20 = ema_series(closes, 20)
    r7 = rsi_series(closes, 7)
    out: Dict[str, List[Tuple[int, int]]] = {}

    out["flagship 10/90+2.5x"] = confl_stoch_fade(candles)
    out["tight 5/95+3.0x"] = confl_variant(candles, 5, 95, 3.0)

    out["stoch14 10/90"] = [(i, 1 if k14[i] < 10 else -1) for i in range(n)
                            if k14[i] == k14[i] and (k14[i] < 10 or k14[i] > 90)]
    out["stoch14 20/80"] = [(i, 1 if k14[i] < 20 else -1) for i in range(n)
                            if k14[i] == k14[i] and (k14[i] < 20 or k14[i] > 80)]
    boll = []
    for i in range(n):
        if mean20[i] == mean20[i]:
            if closes[i] < mean20[i] - 2 * std20[i]:
                boll.append((i, 1))
            elif closes[i] > mean20[i] + 2 * std20[i]:
                boll.append((i, -1))
    out["boll20 k2.0"] = boll
    out["bigbar_fade 2.5x"] = [(i, 1 if closes[i] < candles[i].open else -1)
                               for i in range(n)
                               if atr[i] == atr[i] and (candles[i].high - candles[i].low) > 2.5 * atr[i]]
    kelt = []
    for i in range(n):
        if ema20[i] == ema20[i] and atr[i] == atr[i]:
            if closes[i] < ema20[i] - 3 * atr[i]:
                kelt.append((i, 1))
            elif closes[i] > ema20[i] + 3 * atr[i]:
                kelt.append((i, -1))
    out["keltner k3.0"] = kelt
    bset = {(i, d) for i, d in boll}
    out["confl stoch+boll"] = [(i, d) for i, d in out["stoch14 10/90"] if (i, d) in bset]
    rng50 = []
    for i in range(50, n):
        hi = max(c.high for c in candles[i - 50 + 1:i + 1])
        lo = min(c.low for c in candles[i - 50 + 1:i + 1])
        if hi == lo:
            continue
        pos = (closes[i] - lo) / (hi - lo)
        if pos < 0.05:
            rng50.append((i, 1))
        elif pos > 0.95:
            rng50.append((i, -1))
    out["range50_edge"] = rng50
    out["rsi7 25/75"] = [(i, 1 if r7[i] < 25 else -1) for i in range(n)
                         if r7[i] == r7[i] and (r7[i] < 25 or r7[i] > 75)]
    return out


def part_a_survivors(candles: List[Candle]):
    print("=" * 78)
    print("A) SURVIVOR TEST — every year must be >= 60% (30m, 2.7y, pessimistic)")
    print("=" * 78)
    fams = families(candles)
    for dist in (1500.0, 2500.0):
        print(f"--- dist {dist:.0f} ---")
        for name, sigs in fams.items():
            trades = run_bt(candles, sigs, dist)
            by_y: Dict[int, List[Trade]] = {}
            for t in trades:
                by_y.setdefault(year_of(candles, t), []).append(t)
            yr_wr = {y: sum(x.win for x in ts) / len(ts) * 100
                     for y, ts in by_y.items() if ts}
            ok = all(v >= 60.0 for v in yr_wr.values()) and len(yr_wr) == 3
            tag = "PASS" if ok else "fail"
            yrs = "  ".join(f"{y}:{_wr(ts).strip()}" for y, ts in sorted(by_y.items()))
            print(f"  [{tag}] {name:22s} ALL {_wr(trades)} | {yrs}")


# ------------------------------------------------------------------
def part_b_walkforward(candles: List[Candle]):
    print()
    print("=" * 78)
    print("B) WALK-FORWARD REGIME GATE on flagship (d1500)")
    print("=" * 78)
    trades = run_bt(candles, confl_stoch_fade(candles), 1500.0)
    for win_need in (11, 12):          # of the last 20 closed trades
        taken: List[Trade] = []
        skipped: List[Trade] = []
        hist: List[bool] = []
        for t in trades:
            if len(hist) < 20 or sum(hist[-20:]) >= win_need:
                taken.append(t)
            else:
                skipped.append(t)
            hist.append(t.win)          # outcome known by the next signal (no overlap)
        thr = win_need / 20 * 100
        print(f"  gate >= {thr:.0f}%:  taken {_wr(taken)} netR"
              f"{sum(x.win for x in taken)*2 - len(taken):+d} | "
              f"skipped {_wr(skipped)}")
    print(f"  baseline    :  {_wr(trades)} netR{sum(x.win for x in trades)*2 - len(trades):+d}")


# ------------------------------------------------------------------
def part_c_attribution(candles: List[Candle]):
    print()
    print("=" * 78)
    print("C) REGIME ATTRIBUTION — what does the win depend on?")
    print("=" * 78)
    closes = [c.close for c in candles]
    atr = atr_simple(candles, 14)
    ema200 = ema_series(closes, 200)
    by_year: Dict[int, List[float]] = {}
    for i, c in enumerate(candles):
        if atr[i] == atr[i] and closes[i] > 0:
            y = datetime.fromtimestamp(c.ts / 1000, tz=timezone.utc).year
            by_year.setdefault(y, []).append(atr[i] / closes[i] * 100)
    for y, vals in sorted(by_year.items()):
        vals.sort()
        print(f"  {y}: median ATR/price {vals[len(vals)//2]:.3f}%  "
              f"p90 {vals[int(len(vals)*0.9)]:.3f}%")
    trades = run_bt(candles, confl_stoch_fade(candles), 1500.0)
    # bucket trade outcomes by ATR% and by |stretch from EMA200| at entry
    buckets: Dict[str, List[bool]] = {}
    for t in trades:
        i = t.entry_bar
        if atr[i] != atr[i] or ema200[i] != ema200[i]:
            continue
        atr_pct = atr[i] / closes[i] * 100
        stretch = abs(closes[i] - ema200[i]) / atr[i]
        ka = "atr<0.25%" if atr_pct < 0.25 else ("atr0.25-0.4%" if atr_pct < 0.4 else "atr>0.4%")
        ks = "nearEMA200(<3atr)" if stretch < 3 else ("mid(3-8atr)" if stretch < 8 else "far(>8atr)")
        buckets.setdefault(ka, []).append(t.win)
        buckets.setdefault(ks, []).append(t.win)
    for k in ("atr<0.25%", "atr0.25-0.4%", "atr>0.4%",
              "nearEMA200(<3atr)", "mid(3-8atr)", "far(>8atr)"):
        ws = buckets.get(k, [])
        if ws:
            print(f"  {k:20s}: {sum(ws)}/{len(ws)} = {sum(ws)/len(ws)*100:.1f}%")


if __name__ == "__main__":
    c30 = load_candles("30m")
    part_a_survivors(c30)
    part_b_walkforward(c30)
    part_c_attribution(c30)
