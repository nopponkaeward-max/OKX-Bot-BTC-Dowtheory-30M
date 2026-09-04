"""Round 11 — (a) higher-TF hunt on 4.3y of 4H and 1D data,
(b) liquidation-cascade detection on 30m as a second mechanism,
(c) time-overlap check of any passer against the TIGHT champion.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.lab import (
    Candle, Trade, load_candles, rsi_series, ema_series, sma_std,
    atr_simple, stoch_k,
)
from research.round3 import confl_variant
from research.round7 import run_bt_pct
from research.round9 import _wr, by_year_line, year_of


def eval_pct(candles, name, sigs, pcts, min_trades=30):
    passers = []
    for pct in pcts:
        trades = run_bt_pct(candles, sigs, pct)
        if not trades:
            continue
        by_y: Dict[int, List[Trade]] = {}
        for t in trades:
            by_y.setdefault(year_of(candles, t), []).append(t)
        yr_wr = {y: sum(x.win for x in ts) / len(ts) * 100 for y, ts in by_y.items()}
        n, w = len(trades), sum(t.win for t in trades)
        ok = (w / n * 100 >= 70.0) and all(v >= 60.0 for v in yr_wr.values()) and n >= min_trades
        print(f"  [{'PASS' if ok else 'fail'}] {name:24s} pct{pct:.1f}: "
              f"ALL {_wr(trades)} | {by_year_line(candles, trades)}")
        if ok:
            passers.append((name, pct, trades))
    return passers


def part_a_higher_tf():
    print("=" * 78)
    print("A) HIGHER-TF HUNT — 4H and 1D over 4.3 years (pct distance, floor 500)")
    print("=" * 78)
    passers = []
    for tf, pcts in (("4H", (2.0, 3.0, 4.0)), ("1D", (3.0, 4.0, 5.0))):
        candles = load_candles(tf)
        closes = [c.close for c in candles]
        n = len(candles)
        atr = atr_simple(candles, 14)
        k14 = stoch_k(candles, 14)
        r14 = rsi_series(closes, 14)
        ema20 = ema_series(closes, 20)
        ema50 = ema_series(closes, 50)
        print(f"--- {tf} ({n} bars) ---")
        out: Dict[str, List[Tuple[int, int]]] = {}

        out["exh_tight(5/95,3x)"] = confl_variant(candles, 5, 95, 3.0)
        out["exh_mid(10/90,2.5x)"] = confl_variant(candles, 10, 90, 2.5)
        out["rsi14_rev_25/75"] = [(i, 1 if r14[i] < 25 else -1) for i in range(n)
                                  if r14[i] == r14[i] and (r14[i] < 25 or r14[i] > 75)]
        # MA pullback with trend
        sigs = []
        for i in range(60, n):
            if ema50[i] != ema50[i] or ema20[i] != ema20[i]:
                continue
            if ema50[i] > ema50[i - 10] and closes[i] < ema20[i]:
                sigs.append((i, 1))
            elif ema50[i] < ema50[i - 10] and closes[i] > ema20[i]:
                sigs.append((i, -1))
        out["trend_pullback"] = sigs
        # big-bar fade
        out["bigbar_fade_2.5x"] = [(i, 1 if closes[i] < candles[i].open else -1)
                                   for i in range(n)
                                   if atr[i] == atr[i] and (candles[i].high - candles[i].low) > 2.5 * atr[i]]
        if tf == "1D":
            # day-of-week: long on each weekday (7 variants, honest fishing)
            for wd in range(7):
                sigs = [(i, 1) for i, c in enumerate(candles)
                        if datetime.fromtimestamp(c.ts / 1000, tz=timezone.utc).weekday() == wd]
                out[f"long_wd{wd}"] = sigs
        for name, s in out.items():
            passers += [(tf, *p) for p in eval_pct(candles, name, s, pcts)]
    return passers


def part_b_cascade():
    print()
    print("=" * 78)
    print("B) LIQUIDATION-CASCADE DETECTION on 30m (second mechanism attempt)")
    print("=" * 78)
    candles = load_candles("30m")
    closes = [c.close for c in candles]
    vols = [c.volume for c in candles]
    n = len(candles)
    atr = atr_simple(candles, 14)
    vmean20, _ = sma_std(vols, 20)
    out: Dict[str, List[Tuple[int, int]]] = {}

    # cascade: >=3 same-direction closes, ranges expanding, final bar
    # volume > vm x avg and range > 2xATR -> fade the cascade
    for vm in (3.0, 5.0):
        sigs = []
        for i in range(3, n):
            if atr[i] != atr[i] or vmean20[i] != vmean20[i]:
                continue
            rngs = [candles[j].high - candles[j].low for j in range(i - 2, i + 1)]
            dn = all(closes[j] < closes[j - 1] for j in range(i - 2, i + 1))
            up = all(closes[j] > closes[j - 1] for j in range(i - 2, i + 1))
            if not (dn or up):
                continue
            if not (rngs[2] > rngs[1] > rngs[0] and rngs[2] > 2.0 * atr[i]):
                continue
            if vols[i] <= vm * vmean20[i]:
                continue
            sigs.append((i, 1 if dn else -1))
        out[f"cascade_fade_v{vm}"] = sigs

    # cascade with reclaim wick: same but final bar's wick against move > 40% range
    sigs = []
    for i in range(3, n):
        if atr[i] != atr[i] or vmean20[i] != vmean20[i]:
            continue
        c = candles[i]
        rng = c.high - c.low
        if rng <= 2.0 * atr[i] or vols[i] <= 3.0 * vmean20[i]:
            continue
        dn = all(closes[j] < closes[j - 1] for j in range(i - 2, i + 1))
        up = all(closes[j] > closes[j - 1] for j in range(i - 2, i + 1))
        if dn and (c.close - c.low) > 0.4 * rng:
            sigs.append((i, 1))
        elif up and (c.high - c.close) > 0.4 * rng:
            sigs.append((i, -1))
    out["cascade_wick"] = sigs

    passers = []
    for name, s in out.items():
        passers += [("30m", *p) for p in eval_pct(candles, name, s, (1.5, 2.0, 2.5), min_trades=25)]
    return passers


def part_c_overlap(passers):
    print()
    print("=" * 78)
    print("C) OVERLAP WITH TIGHT CHAMPION (entry within +/-12h)")
    print("=" * 78)
    c30 = load_candles("30m")
    champ = run_bt_pct(c30, confl_variant(c30, 5, 95, 3.0), 2.3)
    champ_ts = [c30[t.entry_bar].ts for t in champ]
    if not passers:
        print("  (no passers to compare)")
        return
    for tf, name, pct, trades in passers:
        cd = load_candles(tf)
        near = 0
        for t in trades:
            ts = cd[t.entry_bar].ts
            if any(abs(ts - x) <= 12 * 3600_000 for x in champ_ts):
                near += 1
        print(f"  {name} {tf} pct{pct}: {near}/{len(trades)} "
              f"({near/len(trades)*100:.0f}%) entries near a TIGHT entry")


if __name__ == "__main__":
    p = part_a_higher_tf()
    p += part_b_cascade()
    part_c_overlap(p)
