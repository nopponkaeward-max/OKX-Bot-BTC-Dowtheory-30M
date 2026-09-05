"""Round 7 — deep OOS on 2.7 years of 30m data.

(a) flagship by calendar year, fixed vs price-proportional distance
    (pct of entry price with a 500-pt floor — still honours dist >= 500),
(b) rolling 50-trade winrate curve (regime drift),
(c) new families: two-bar reversal, volume-climax wick, Keltner re-entry.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.lab import (
    Candle, Result, Trade, run_bt, load_candles, leaderboard, MIN_TRADES,
    ema_series, sma_std, atr_simple, stoch_k,
)
from research.validate import confl_stoch_fade


def _wr(trades) -> str:
    n = len(trades)
    if not n:
        return "0t"
    w = sum(t.win for t in trades)
    return f"{n:>4d}t {w / n * 100:5.1f}% netR{w - (n - w):+d}"


def run_bt_pct(candles: List[Candle], signals: List[Tuple[int, int]],
               pct: float, floor: float = 500.0) -> List[Trade]:
    """Like run_bt but distance = max(pct% of entry price, floor)."""
    sig: Dict[int, int] = {}
    for i, d in signals:
        sig.setdefault(i, d)
    trades: List[Trade] = []
    open_tr: Optional[Tuple[int, float, float, float, int]] = None
    for i, c in enumerate(candles):
        was_open = open_tr is not None
        if open_tr:
            d, e, sl, tp, b = open_tr
            hit_sl = (c.low <= sl) if d > 0 else (c.high >= sl)
            hit_tp = (c.high >= tp) if d > 0 else (c.low <= tp)
            if hit_sl or hit_tp:
                trades.append(Trade(d, e, sl, tp, b, i,
                                    hit_tp and not hit_sl, hit_sl and hit_tp))
                open_tr = None
        if not was_open and i > 0 and (i - 1) in sig:
            d = sig[i - 1]
            e = c.open
            dist = max(e * pct / 100.0, floor)
            sl, tp = e - d * dist, e + d * dist
            hit_sl = (c.low <= sl) if d > 0 else (c.high >= sl)
            hit_tp = (c.high >= tp) if d > 0 else (c.low <= tp)
            if hit_sl or hit_tp:
                trades.append(Trade(d, e, sl, tp, i, i,
                                    hit_tp and not hit_sl, hit_sl and hit_tp))
            else:
                open_tr = (d, e, sl, tp, i)
    return trades


def year_of(candles, t: Trade) -> int:
    return datetime.fromtimestamp(candles[t.entry_bar].ts / 1000, tz=timezone.utc).year


def part_a_deep_oos(candles: List[Candle]):
    print("=" * 74)
    print("A) DEEP OOS — flagship by calendar year (2.7y of 30m, pessimistic)")
    print("=" * 74)
    sigs = confl_stoch_fade(candles)
    variants = [("fixed d1000", lambda: run_bt(candles, sigs, 1000.0)),
                ("fixed d1500", lambda: run_bt(candles, sigs, 1500.0)),
                ("fixed d2000", lambda: run_bt(candles, sigs, 2000.0)),
                ("pct 1.0% (>=500)", lambda: run_bt_pct(candles, sigs, 1.0)),
                ("pct 1.5% (>=500)", lambda: run_bt_pct(candles, sigs, 1.5)),
                ("pct 2.0% (>=500)", lambda: run_bt_pct(candles, sigs, 2.0))]
    for name, fn in variants:
        trades = fn()
        by_y: Dict[int, List[Trade]] = {}
        for t in trades:
            by_y.setdefault(year_of(candles, t), []).append(t)
        parts = "  ".join(f"{y}: {_wr(ts).strip()}" for y, ts in sorted(by_y.items()))
        print(f"  {name:17s} ALL {_wr(trades)}")
        print(f"     {parts}")


def part_b_rolling(candles: List[Candle]):
    print()
    print("=" * 74)
    print("B) ROLLING 50-TRADE WINRATE — flagship pct 1.5% (regime drift)")
    print("=" * 74)
    trades = run_bt_pct(candles, confl_stoch_fade(candles), 1.5)
    wins = [1 if t.win else 0 for t in trades]
    for k in range(50, len(trades) + 1, 15):
        w = sum(wins[k - 50:k])
        d = datetime.fromtimestamp(candles[trades[k - 1].entry_bar].ts / 1000,
                                   tz=timezone.utc)
        bar = "#" * int(w / 50 * 40)
        print(f"  ..{d:%Y-%m}  {w}/50 = {w*2}%  {bar}")


def part_c_new_families(candles_by_tf: Dict[str, List[Candle]]):
    print()
    print("=" * 74)
    print("C) NEW FAMILIES: two-bar reversal, volume-climax wick, Keltner re-entry")
    print("=" * 74)
    results: List[Result] = []
    for tf, candles in candles_by_tf.items():
        closes = [c.close for c in candles]
        vols = [c.volume for c in candles]
        n = len(candles)
        atr = atr_simple(candles, 14)
        ema20 = ema_series(closes, 20)
        vmean20, _ = sma_std(vols, 20)
        out: Dict[str, List[Tuple[int, int]]] = {}

        # two-bar reversal: bar closes beyond the PREVIOUS bar's full range
        sigs = []
        for i in range(1, n):
            if closes[i] > candles[i - 1].high and closes[i - 1] < candles[i - 1].open:
                sigs.append((i, 1))
            elif closes[i] < candles[i - 1].low and closes[i - 1] > candles[i - 1].open:
                sigs.append((i, -1))
        out["twobar_rev"] = sigs

        # volume-climax wick: vol > 3x avg AND dominant wick against the move
        sigs = []
        for i, c in enumerate(candles):
            rng = c.high - c.low
            if rng <= 0 or vmean20[i] != vmean20[i] or vols[i] <= 3.0 * vmean20[i]:
                continue
            lower = min(c.open, c.close) - c.low
            upper = c.high - max(c.open, c.close)
            if lower > 0.5 * rng:
                sigs.append((i, 1))
            elif upper > 0.5 * rng:
                sigs.append((i, -1))
        out["volclimax_wick"] = sigs

        # Keltner re-entry: prior close beyond EMA20 +/- 3*ATR, this close back inside
        sigs = []
        for i in range(1, n):
            if ema20[i] != ema20[i] or atr[i] != atr[i]:
                continue
            lo_b, hi_b = ema20[i] - 3 * atr[i], ema20[i] + 3 * atr[i]
            lo_p = ema20[i - 1] - 3 * atr[i - 1] if atr[i - 1] == atr[i - 1] else None
            hi_p = ema20[i - 1] + 3 * atr[i - 1] if atr[i - 1] == atr[i - 1] else None
            if lo_p is None:
                continue
            if closes[i - 1] < lo_p and closes[i] > lo_b:
                sigs.append((i, 1))
            elif closes[i - 1] > hi_p and closes[i] < hi_b:
                sigs.append((i, -1))
        out["keltner_reentry"] = sigs

        for name, s in out.items():
            for dist in (1000.0, 1500.0, 2000.0, 3000.0):
                results.append(Result(name=name, tf=tf, dist=dist,
                                      trades=run_bt(candles, s, dist)))
    print(leaderboard(results, top=14))
    hits = [r for r in results if r.n >= MIN_TRADES and r.winrate >= 70.0]
    print(f"\n>=70% candidates: {len(hits)}")
    for r in hits:
        print(f"  {r.name} {r.tf} d{r.dist:.0f}: {r.n}t {r.winrate:.1f}% netR{r.net_r:+.0f}")


if __name__ == "__main__":
    c30 = load_candles("30m")
    part_a_deep_oos(c30)
    part_b_rolling(c30)
    part_c_new_families({"30m": c30, "1H": load_candles("1H")})
