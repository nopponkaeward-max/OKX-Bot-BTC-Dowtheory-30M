"""Round 4 — (a) 1m re-resolution of flagship ambiguous bars,
(b) flagship+Keltner confluence & volatility-regime filter,
(c) new families: gap-fill, round-number bounce, multi-TF stoch alignment,
(d) flagship ported to 15m/1H/2H with ATR-proportional distances.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.lab import (
    Candle, Result, run_bt, load_candles, leaderboard, MIN_TRADES,
    ema_series, sma_std, atr_simple, stoch_k,
)
from research.validate import confl_stoch_fade, month_of


def _wr(trades) -> str:
    n = len(trades)
    if not n:
        return "0t"
    w = sum(t.win for t in trades)
    return f"{n}t {w / n * 100:.1f}% netR{w - (n - w):+d}"


# ------------------------------------------------------------------
def part_a_1m_recheck():
    print("=" * 70)
    print("A) 1m INTRABAR RE-CHECK of flagship ambiguous losses (upper bound)")
    print("=" * 70)
    from bot.config import load_config
    from bot.okx_client import OKXClient
    from bot import data as datamod
    from bot.engine import ltf_first_hit

    cfg = load_config("config.yaml")
    client = OKXClient(demo=cfg.exchange.demo, base_url=cfg.exchange.base_url)
    candles = load_candles("30m")
    sigs = confl_stoch_fade(candles)
    provider = datamod.LtfProvider(client, "BTC-USDT-SWAP", "30m", "1m")
    for dist in (1000.0, 1500.0):
        trades = run_bt(candles, sigs, dist)
        amb = [t for t in trades if t.ambiguous and not t.win]
        flipped = failed = nodata = 0
        for t in amb:
            sub = provider(candles[t.close_bar].ts)
            if not sub:
                nodata += 1
            elif ltf_first_hit(sub, t.dir > 0, t.sl, t.tp) == 2:
                flipped += 1
            else:
                failed += 1
        n = len(trades)
        w = sum(t.win for t in trades)
        print(f"  d{dist:.0f}: pessimistic {w}/{n} = {w/n*100:.1f}% | ambiguous {len(amb)} "
              f"-> TP-first {flipped}, SL-first {failed}, no-1m-data {nodata} "
              f"| upper bound {(w+flipped)}/{n} = {(w+flipped)/n*100:.1f}%")


# ------------------------------------------------------------------
def part_b_filters():
    print()
    print("=" * 70)
    print("B) FLAGSHIP + FILTERS (30m, 15 months, pessimistic)")
    print("=" * 70)
    candles = load_candles("30m")
    closes = [c.close for c in candles]
    n = len(candles)
    atr = atr_simple(candles, 14)
    ema20 = ema_series(closes, 20)
    atr_ma, _ = sma_std([a if a == a else 0.0 for a in atr], 100)
    base = confl_stoch_fade(candles)

    variants: Dict[str, List[Tuple[int, int]]] = {"flagship(base)": base}
    variants["+keltner3"] = [
        (i, d) for i, d in base
        if ema20[i] == ema20[i] and atr[i] == atr[i] and (
            (d > 0 and closes[i] < ema20[i] - 3 * atr[i]) or
            (d < 0 and closes[i] > ema20[i] + 3 * atr[i]))]
    variants["+highvol(atr>1.2xavg)"] = [
        (i, d) for i, d in base
        if atr_ma[i] == atr_ma[i] and atr_ma[i] > 0 and atr[i] > 1.2 * atr_ma[i]]
    variants["+lowvol(atr<1.2xavg)"] = [
        (i, d) for i, d in base
        if atr_ma[i] == atr_ma[i] and atr_ma[i] > 0 and atr[i] <= 1.2 * atr_ma[i]]
    for name, s in variants.items():
        for dist in (1500.0, 2500.0):
            print(f"  {name:26s} d{dist:.0f}: {_wr(run_bt(candles, s, dist))}")


# ------------------------------------------------------------------
def part_c_new_families():
    print()
    print("=" * 70)
    print("C) NEW FAMILIES: gap-fill, round-number bounce, multi-TF stoch")
    print("=" * 70)
    results: List[Result] = []
    c2h = load_candles("2H")
    k2h_series = stoch_k(c2h, 14)
    # map: 2H open-ts -> stoch of that closed 2H bar
    k2h_by_ts = {c.ts: k2h_series[i] for i, c in enumerate(c2h)}

    for tf in ("30m", "1H"):
        candles = load_candles(tf)
        closes = [c.close for c in candles]
        n = len(candles)
        atr = atr_simple(candles, 14)
        k14 = stoch_k(candles, 14)
        out: Dict[str, List[Tuple[int, int]]] = {}

        # gap-fill: open deviates from prev close by > 0.5*ATR -> fade toward fill
        sigs = []
        for i in range(1, n):
            if atr[i] != atr[i]:
                continue
            gap = candles[i].open - candles[i - 1].close
            if abs(gap) > 0.5 * atr[i]:
                sigs.append((i, -1 if gap > 0 else 1))
        out["gapfill_0.5atr"] = sigs

        # round-number bounce: sweep a 5000-multiple intrabar, close back beyond it
        for step in (5000, 10000):
            sigs = []
            for i, c in enumerate(candles):
                lvl_lo = (int(c.low) // step) * step + step   # first level above low
                if c.low < lvl_lo <= c.close and c.open >= lvl_lo:
                    sigs.append((i, 1))            # dipped through level, reclaimed
                lvl_hi = (int(c.high) // step) * step          # last level below high
                if c.high > lvl_hi >= c.close and c.open <= lvl_hi:
                    sigs.append((i, -1))
            out[f"round{step}_bounce"] = sigs

        # multi-TF: this TF stoch extreme AND last CLOSED 2H stoch confirming
        sigs = []
        for i in range(n):
            if k14[i] != k14[i]:
                continue
            close_ms = candles[i].ts + (1800_000 if tf == "30m" else 3600_000)
            prev2h_ts = ((close_ms // 7200_000) - 1) * 7200_000
            k2 = k2h_by_ts.get(prev2h_ts)
            if k2 is None or k2 != k2:
                continue
            if k14[i] < 10 and k2 < 25:
                sigs.append((i, 1))
            elif k14[i] > 90 and k2 > 75:
                sigs.append((i, -1))
        out["mtf_stoch_10/25"] = sigs

        for name, s in out.items():
            for dist in (1000.0, 1500.0, 2000.0, 2500.0, 3000.0):
                results.append(Result(name=name, tf=tf, dist=dist,
                                      trades=run_bt(candles, s, dist)))
    print(leaderboard(results, top=15))


# ------------------------------------------------------------------
def part_d_tf_ports():
    print()
    print("=" * 70)
    print("D) FLAGSHIP PORTED ACROSS TFs (same rule, ATR-proportional dists)")
    print("=" * 70)
    for tf, dists in (("15m", (500.0, 750.0, 1000.0)),
                      ("30m", (1500.0,)),
                      ("1H", (1500.0, 2000.0, 3000.0)),
                      ("2H", (2000.0, 3000.0, 4000.0))):
        candles = load_candles(tf)
        sigs = confl_stoch_fade(candles)
        span_d = (candles[-1].ts - candles[0].ts) / 86_400_000
        for dist in dists:
            print(f"  {tf:>3s} d{dist:>4.0f} ({span_d:.0f}d data): {_wr(run_bt(candles, sigs, dist))}")


if __name__ == "__main__":
    part_a_1m_recheck()
    part_b_filters()
    part_c_new_families()
    part_d_tf_ports()
