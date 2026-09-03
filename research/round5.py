"""Round 5 — (a) limit-entry variant of the Exhaustion Fade,
(b) portfolio stats (equity in R, max drawdown, streaks, day-of-week),
(c) 30m+1H overlap check, (d) new families: failed-breakout fade,
squeeze-expansion, first-hour range.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.lab import (
    Candle, Result, Trade, run_bt, load_candles, leaderboard, MIN_TRADES,
    sma_std, atr_simple, stoch_k,
)
from research.validate import confl_stoch_fade

DAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _wr(trades) -> str:
    n = len(trades)
    if not n:
        return "0t"
    w = sum(t.win for t in trades)
    return f"{n}t {w / n * 100:.1f}% netR{w - (n - w):+d}"


# ------------------------------------------------------------------
# (a) limit-entry backtester: limit rests at a retrace into the climax bar
# ------------------------------------------------------------------
def run_bt_limit(candles: List[Candle], signals: List[Tuple[int, int]],
                 dist: float, retrace: float, expire_bars: int = 16) -> List[Trade]:
    sig: Dict[int, int] = {}
    for i, d in signals:
        sig.setdefault(i, d)
    trades: List[Trade] = []
    pending: Optional[Tuple[int, float, int]] = None   # (dir, limit_px, signal_bar)
    open_tr: Optional[Tuple[int, float, float, float, int]] = None
    for i, c in enumerate(candles):
        was_open = open_tr is not None
        if open_tr:
            d, e, sl, tp, b = open_tr
            hit_sl = (c.low <= sl) if d > 0 else (c.high >= sl)
            hit_tp = (c.high >= tp) if d > 0 else (c.low <= tp)
            if hit_sl or hit_tp:
                win = hit_tp and not hit_sl
                trades.append(Trade(d, e, sl, tp, b, i, win, hit_sl and hit_tp))
                open_tr = None
        if not was_open and pending is not None:
            d, px, sb = pending
            if i - sb > expire_bars:
                pending = None
            else:
                filled = (c.low <= px) if d > 0 else (c.high >= px)
                if filled:
                    e = px
                    sl, tp = e - d * dist, e + d * dist
                    # fill bar: only a SL touch counts (order unknowable — pessimistic)
                    hit_sl = (c.low <= sl) if d > 0 else (c.high >= sl)
                    if hit_sl:
                        trades.append(Trade(d, e, sl, tp, i, i, False, True))
                    else:
                        open_tr = (d, e, sl, tp, i)
                    pending = None
        if pending is None and open_tr is None and not was_open and i in sig:
            d = sig[i]
            rng = c.high - c.low
            px = c.close - d * retrace * rng
            pending = (d, px, i)
    return trades


def part_a_limit_entry():
    print("=" * 70)
    print("A) LIMIT-ENTRY VARIANT (retrace into climax bar, expire 16 bars)")
    print("=" * 70)
    candles = load_candles("30m")
    sigs = confl_stoch_fade(candles)
    print(f"  market entry        d1500: {_wr(run_bt(candles, sigs, 1500.0))}   <- baseline")
    for retrace in (0.25, 0.4, 0.6):
        for dist in (1500.0, 2500.0):
            t = run_bt_limit(candles, sigs, dist, retrace)
            print(f"  limit retrace {retrace:.2f}  d{dist:.0f}: {_wr(t)}")


# ------------------------------------------------------------------
# (b) portfolio stats
# ------------------------------------------------------------------
def part_b_portfolio():
    print()
    print("=" * 70)
    print("B) PORTFOLIO STATS — flagship 30m d1500 (15 months)")
    print("=" * 70)
    candles = load_candles("30m")
    trades = run_bt(candles, confl_stoch_fade(candles), 1500.0)
    eq = peak = dd = 0.0
    streak = worst_streak = 0
    for t in trades:
        eq += 1 if t.win else -1
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        streak = streak + 1 if not t.win else 0
        worst_streak = max(worst_streak, streak)
    n = len(trades)
    w = sum(t.win for t in trades)
    print(f"  trades {n}, win {w/n*100:.1f}%, final equity {eq:+.0f}R")
    print(f"  max drawdown {dd:.0f}R, max consecutive losses {worst_streak}")
    by_d: Dict[int, List[bool]] = {}
    for t in trades:
        wd = datetime.fromtimestamp(candles[t.entry_bar].ts / 1000, tz=timezone.utc).weekday()
        by_d.setdefault(wd, []).append(t.win)
    for wd in sorted(by_d):
        ws = by_d[wd]
        print(f"  {DAY[wd]}: {sum(ws)}/{len(ws)} = {sum(ws)/len(ws)*100:.0f}%  R{2*sum(ws)-len(ws):+d}")


# ------------------------------------------------------------------
# (c) 30m + 1H overlap
# ------------------------------------------------------------------
def part_c_overlap():
    print()
    print("=" * 70)
    print("C) 30m + 1H PORTFOLIO OVERLAP")
    print("=" * 70)
    c30 = load_candles("30m")
    c1h = load_candles("1H")
    t30 = run_bt(c30, confl_stoch_fade(c30), 1500.0)
    t1h = run_bt(c1h, confl_stoch_fade(c1h), 2000.0)
    iv30 = [(c30[t.entry_bar].ts, c30[t.close_bar].ts, t.win) for t in t30]
    overlap = 0
    for t in t1h:
        a, b = c1h[t.entry_bar].ts, c1h[t.close_bar].ts
        if any(not (b < x or a > y) for x, y, _ in iv30):
            overlap += 1
    print(f"  30m: {_wr(t30)} | 1H: {_wr(t1h)}")
    print(f"  1H trades overlapping an open 30m trade: {overlap}/{len(t1h)} "
          f"({overlap/len(t1h)*100:.0f}%) -> combined exposure mostly duplicated"
          if t1h else "")


# ------------------------------------------------------------------
# (d) new families
# ------------------------------------------------------------------
def part_d_new_families():
    print()
    print("=" * 70)
    print("D) NEW FAMILIES: failed-breakout fade, squeeze-expansion, first-hour range")
    print("=" * 70)
    results: List[Result] = []
    for tf in ("30m", "1H"):
        candles = load_candles(tf)
        closes = [c.close for c in candles]
        n = len(candles)
        out: Dict[str, List[Tuple[int, int]]] = {}

        # failed breakout: bar i closes beyond N-bar extreme, bar i+1 closes back
        for look in (20, 50):
            sigs = []
            for i in range(look + 1, n):
                prev_hi = max(c.close for c in candles[i - look - 1:i - 1])
                prev_lo = min(c.close for c in candles[i - look - 1:i - 1])
                if closes[i - 1] > prev_hi and closes[i] < prev_hi:
                    sigs.append((i, -1))
                elif closes[i - 1] < prev_lo and closes[i] > prev_lo:
                    sigs.append((i, 1))
            out[f"fakeout{look}"] = sigs

        # squeeze-expansion: BB width at 100-bar low, then close breaks a band
        mean20, std20 = sma_std(closes, 20)
        width = [4 * s / m if m == m and m > 0 else float("nan")
                 for m, s in zip(mean20, std20)]
        for mode in ("follow", "fade"):
            sigs = []
            for i in range(120, n):
                ws = [w for w in width[i - 100:i] if w == w]
                if not ws or width[i - 1] != width[i - 1]:
                    continue
                if width[i - 1] > min(ws) * 1.1:
                    continue                      # not squeezed on the prior bar
                d = 0
                if closes[i] > mean20[i] + 2 * std20[i]:
                    d = 1
                elif closes[i] < mean20[i] - 2 * std20[i]:
                    d = -1
                if d:
                    sigs.append((i, d if mode == "follow" else -d))
            out[f"squeeze_{mode}"] = sigs

        # first-hour range break (00:00-01:00 UTC), one signal per day
        sigs_f: List[Tuple[int, int]] = []
        sigs_r: List[Tuple[int, int]] = []
        day_key = None
        rhi = rlo = None
        done = False
        for i, c in enumerate(candles):
            dt = datetime.fromtimestamp(c.ts / 1000, tz=timezone.utc)
            if dt.date() != day_key:
                day_key, rhi, rlo, done = dt.date(), None, None, False
            if dt.hour == 0:
                rhi = c.high if rhi is None else max(rhi, c.high)
                rlo = c.low if rlo is None else min(rlo, c.low)
            elif rhi is not None and not done:
                if c.close > rhi:
                    sigs_f.append((i, 1))
                    sigs_r.append((i, -1))
                    done = True
                elif c.close < rlo:
                    sigs_f.append((i, -1))
                    sigs_r.append((i, 1))
                    done = True
        out["h1range_follow"] = sigs_f
        out["h1range_fade"] = sigs_r

        for name, s in out.items():
            for dist in (1000.0, 1500.0, 2000.0, 2500.0, 3000.0):
                results.append(Result(name=name, tf=tf, dist=dist,
                                      trades=run_bt(candles, s, dist)))
    print(leaderboard(results, top=15))
    hits = [r for r in results if r.n >= MIN_TRADES and r.winrate >= 70.0]
    print(f"\n>=70% candidates: {len(hits)}")
    for r in hits:
        print(f"  {r.name} {r.tf} d{r.dist:.0f}: {r.n}t {r.winrate:.1f}% netR{r.net_r:+.0f}")


if __name__ == "__main__":
    part_a_limit_entry()
    part_b_portfolio()
    part_c_overlap()
    part_d_new_families()
