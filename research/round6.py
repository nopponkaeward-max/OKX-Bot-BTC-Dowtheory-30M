"""Round 6 — (a) funding-rate strategies (OKX funding-rate-history),
(b) funding as a filter on the flagship, (c) candle patterns
(engulfing-after-streak, doji-at-extreme), (d) weekend/Monday reversion.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.lab import (
    Candle, Result, run_bt, load_candles, leaderboard, MIN_TRADES,
    atr_simple, DATA_DIR,
)
from research.validate import confl_stoch_fade

FUND_PATH = os.path.join(DATA_DIR, "funding.json")


def _wr(trades) -> str:
    n = len(trades)
    if not n:
        return "0t"
    w = sum(t.win for t in trades)
    return f"{n}t {w / n * 100:.1f}% netR{w - (n - w):+d}"


# ------------------------------------------------------------------
def fetch_funding() -> List[Tuple[int, float]]:
    """[(funding_time_ms, rate), ...] ascending; cached."""
    if os.path.exists(FUND_PATH):
        with open(FUND_PATH) as fh:
            return [tuple(r) for r in json.load(fh)]
    from bot.config import load_config
    from bot.okx_client import OKXClient
    cfg = load_config("config.yaml")
    client = OKXClient(demo=cfg.exchange.demo, base_url=cfg.exchange.base_url)
    rows: List[Tuple[int, float]] = []
    after: Optional[int] = None
    for _ in range(40):
        params = {"instId": "BTC-USDT-SWAP", "limit": 100}
        if after:
            params["after"] = str(after)
        batch = client._request("GET", "/api/v5/public/funding-rate-history", params=params)
        if not batch:
            break
        for b in batch:
            rows.append((int(b["fundingTime"]), float(b["fundingRate"])))
        after = min(int(b["fundingTime"]) for b in batch)
        time.sleep(0.25)
        if len(batch) < 100:
            break
    rows = sorted(set(rows))
    with open(FUND_PATH, "w") as fh:
        json.dump(rows, fh)
    return rows


def part_a_funding(candles: List[Candle]):
    print("=" * 70)
    print("A) FUNDING-RATE STRATEGIES (30m)")
    print("=" * 70)
    funding = fetch_funding()
    print(f"  funding records: {len(funding)} "
          f"({datetime.fromtimestamp(funding[0][0]/1000, tz=timezone.utc):%Y-%m-%d} .. "
          f"{datetime.fromtimestamp(funding[-1][0]/1000, tz=timezone.utc):%Y-%m-%d})")
    # signal bar = the bar whose CLOSE coincides with the funding time
    close_ts_to_idx = {c.ts + 1800_000: i for i, c in enumerate(candles)}
    results: List[Result] = []
    for thr in (0.0003, 0.0005, 0.001):
        fade, follow = [], []
        for ft, rate in funding:
            i = close_ts_to_idx.get(ft)
            if i is None:
                continue
            if rate >= thr:
                fade.append((i, -1))
                follow.append((i, 1))
            elif rate <= -thr:
                fade.append((i, 1))
                follow.append((i, -1))
        for name, s in ((f"fund_fade_{thr}", fade), (f"fund_follow_{thr}", follow)):
            for dist in (1000.0, 1500.0, 2000.0, 3000.0):
                results.append(Result(name=name, tf="30m", dist=dist,
                                      trades=run_bt(candles, s, dist)))
    print(leaderboard(results, top=12, min_trades=20))
    return funding


def part_b_funding_filter(candles: List[Candle], funding: List[Tuple[int, float]]):
    print()
    print("=" * 70)
    print("B) FLAGSHIP SPLIT BY FUNDING REGIME AT ENTRY (30m d1500)")
    print("=" * 70)
    trades = run_bt(candles, confl_stoch_fade(candles), 1500.0)
    fts = [f[0] for f in funding]
    import bisect
    groups: Dict[str, List[bool]] = {"crowd-with(+)": [], "neutral": [], "crowd-against(-)": []}
    for t in trades:
        ts = candles[t.entry_bar].ts
        k = bisect.bisect_right(fts, ts) - 1
        if k < 0:
            continue
        rate = funding[k][1]
        signed = rate * t.dir      # >0: funding pays against our side's crowd
        if signed > 0.0001:
            groups["crowd-with(+)"].append(t.win)
        elif signed < -0.0001:
            groups["crowd-against(-)"].append(t.win)
        else:
            groups["neutral"].append(t.win)
    for g, ws in groups.items():
        if ws:
            print(f"  {g:18s}: {sum(ws)}/{len(ws)} = {sum(ws)/len(ws)*100:.1f}%")


def part_c_candles_and_monday(candles_by_tf: Dict[str, List[Candle]]):
    print()
    print("=" * 70)
    print("C) CANDLE PATTERNS + WEEKEND/MONDAY REVERSION")
    print("=" * 70)
    results: List[Result] = []
    for tf, candles in candles_by_tf.items():
        closes = [c.close for c in candles]
        n = len(candles)
        atr = atr_simple(candles, 14)
        out: Dict[str, List[Tuple[int, int]]] = {}

        # engulfing after a >=3-bar streak
        sigs = []
        for i in range(4, n):
            body = abs(closes[i] - candles[i].open)
            prev_body = abs(closes[i - 1] - candles[i - 1].open)
            if body <= prev_body:
                continue
            up_streak = all(closes[j] > closes[j - 1] for j in range(i - 3, i))
            dn_streak = all(closes[j] < closes[j - 1] for j in range(i - 3, i))
            if dn_streak and closes[i] > candles[i].open and closes[i] > candles[i - 1].open:
                sigs.append((i, 1))
            elif up_streak and closes[i] < candles[i].open and closes[i] < candles[i - 1].open:
                sigs.append((i, -1))
        out["engulf_after3"] = sigs

        # doji at a 50-bar extreme
        sigs = []
        for i in range(50, n):
            rng = candles[i].high - candles[i].low
            if rng <= 0 or atr[i] != atr[i]:
                continue
            body = abs(closes[i] - candles[i].open)
            if body > 0.15 * rng or rng < 0.8 * atr[i]:
                continue
            hi50 = max(c.high for c in candles[i - 50:i])
            lo50 = min(c.low for c in candles[i - 50:i])
            if candles[i].high >= hi50:
                sigs.append((i, -1))
            elif candles[i].low <= lo50:
                sigs.append((i, 1))
        out["doji_at_extreme"] = sigs

        # Monday-open reversion: fade the weekend (Fri 00:00 -> Mon 00:00) move
        sigs = []
        idx_by_ts = {c.ts: i for i, c in enumerate(candles)}
        for i, c in enumerate(candles):
            dt = datetime.fromtimestamp(c.ts / 1000, tz=timezone.utc)
            if dt.weekday() == 0 and dt.hour == 0 and dt.minute == 0:
                fri = c.ts - 3 * 86_400_000
                j = idx_by_ts.get(fri)
                if j is not None and i > 0:
                    move = closes[i - 1] - closes[j]
                    if abs(move) > 0:
                        sigs.append((i - 1, -1 if move > 0 else 1))
        out["monday_fade_weekend"] = sigs

        for name, s in out.items():
            for dist in (1000.0, 1500.0, 2000.0, 3000.0):
                results.append(Result(name=name, tf=tf, dist=dist,
                                      trades=run_bt(candles, s, dist)))
    print(leaderboard(results, top=14, min_trades=20))
    hits = [r for r in results if r.n >= MIN_TRADES and r.winrate >= 70.0]
    print(f"\n>=70% candidates (>=30t): {len(hits)}")
    for r in hits:
        print(f"  {r.name} {r.tf} d{r.dist:.0f}: {r.n}t {r.winrate:.1f}% netR{r.net_r:+.0f}")


if __name__ == "__main__":
    c30 = load_candles("30m")
    funding = part_a_funding(c30)
    part_b_funding_filter(c30, funding)
    part_c_candles_and_monday({"30m": c30, "1H": load_candles("1H")})
