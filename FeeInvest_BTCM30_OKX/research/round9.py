"""Round 9 — full validation battery for "Exhaustion Fade TIGHT"
(%K(14) <5/>95 + range > 3.0*ATR(14), 30m) on 4.3 years incl. the 2022-23
bear market. Cross-era tests use price-proportional distance (floor 500).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.lab import Candle, Trade, run_bt, load_candles
from research.round3 import confl_variant
from research.round7 import run_bt_pct
from research.validate import month_of


def _wr(trades) -> str:
    n = len(trades)
    if not n:
        return "   0t"
    w = sum(t.win for t in trades)
    return f"{n:>4d}t {w / n * 100:5.1f}% netR{w - (n - w):+d}"


def year_of(candles, t: Trade) -> int:
    return datetime.fromtimestamp(candles[t.entry_bar].ts / 1000, tz=timezone.utc).year


def by_year_line(candles, trades) -> str:
    by_y: Dict[int, List[Trade]] = {}
    for t in trades:
        by_y.setdefault(year_of(candles, t), []).append(t)
    return "  ".join(
        f"{y}:{sum(x.win for x in ts)}/{len(ts)}={sum(x.win for x in ts)/len(ts)*100:.0f}%"
        for y, ts in sorted(by_y.items()))


def main():
    candles = load_candles("30m")
    print(f"data: {len(candles)} bars "
          f"({datetime.fromtimestamp(candles[0].ts/1000, tz=timezone.utc):%Y-%m-%d} .. "
          f"{datetime.fromtimestamp(candles[-1].ts/1000, tz=timezone.utc):%Y-%m-%d})")
    tight = confl_variant(candles, 5, 95, 3.0)

    print()
    print("=" * 78)
    print("A) TIGHT across 4.3 years — price-proportional distance (floor 500)")
    print("=" * 78)
    for pct in (1.5, 2.0, 2.3, 2.5):
        trades = run_bt_pct(candles, tight, pct)
        print(f"  pct {pct:.1f}%: ALL {_wr(trades)}")
        print(f"     {by_year_line(candles, trades)}")
    print("  (fixed d2500, for reference — only meaningful 2024+):")
    tr_fixed = run_bt(candles, tight, 2500.0)
    print(f"     {by_year_line(candles, tr_fixed)}")

    print()
    print("=" * 78)
    print("B) PLATEAU (pct 2.3%, 4.3y): stoch x ATR-mult neighborhood")
    print("=" * 78)
    for lo, hi in ((4, 96), (5, 95), (6, 94)):
        for mult in (2.75, 3.0, 3.25):
            sigs = confl_variant(candles, lo, hi, mult)
            trades = run_bt_pct(candles, sigs, 2.3)
            print(f"  {lo}/{hi} x{mult}: ALL {_wr(trades)} | {by_year_line(candles, trades)}")

    print()
    print("=" * 78)
    print("C) QUALITY — pct 2.3%: equity/DD, sides, sessions, ambiguity")
    print("=" * 78)
    trades = run_bt_pct(candles, tight, 2.3)
    eq = peak = dd = 0.0
    streak = worst = 0
    for t in trades:
        eq += 1 if t.win else -1
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        streak = streak + 1 if not t.win else 0
        worst = max(worst, streak)
    print(f"  equity {eq:+.0f}R, max drawdown {dd:.0f}R, max consec losses {worst}")
    longs = [t for t in trades if t.dir > 0]
    shorts = [t for t in trades if t.dir < 0]
    print(f"  LONG {_wr(longs)} | SHORT {_wr(shorts)}")
    sess: Dict[str, List[bool]] = {}
    for t in trades:
        h = datetime.fromtimestamp(candles[t.entry_bar].ts / 1000, tz=timezone.utc).hour
        k = "asia(0-8)" if h < 8 else ("eu(8-16)" if h < 16 else "us(16-24)")
        sess.setdefault(k, []).append(t.win)
    for k, ws in sorted(sess.items()):
        print(f"  {k}: {sum(ws)}/{len(ws)} = {sum(ws)/len(ws)*100:.1f}%")
    amb = sum(1 for t in trades if t.ambiguous)
    print(f"  ambiguous double-touch bars counted as loss: {amb}/{len(trades)}")
    hold = sum(t.close_bar - t.entry_bar for t in trades) / len(trades)
    print(f"  avg hold {hold:.0f} bars (~{hold/2:.0f} h) | "
          f"trades/month ~{len(trades)/51.5:.1f}")

    print()
    print("=" * 78)
    print("D) LAST-15-MONTH MONTHLY CURVE (pct 2.3%)")
    print("=" * 78)
    cutoff = candles[-1].ts - 15 * 30 * 86_400_000
    by_m: Dict[str, List[bool]] = {}
    for t in trades:
        ts = candles[t.entry_bar].ts
        if ts >= cutoff:
            by_m.setdefault(month_of(ts), []).append(t.win)
    for m in sorted(by_m):
        ws = by_m[m]
        print(f"  {m}: {sum(ws)}/{len(ws)}  R{2*sum(ws)-len(ws):+d}")

    print()
    print("=" * 78)
    print("E) 1H PORT (tight rule, pct 2.3%, data Aug 2025+)")
    print("=" * 78)
    c1h = load_candles("1H")
    t1h = run_bt_pct(c1h, confl_variant(c1h, 5, 95, 3.0), 2.3)
    print(f"  1H: {_wr(t1h)} | {by_year_line(c1h, t1h)}")


if __name__ == "__main__":
    main()
