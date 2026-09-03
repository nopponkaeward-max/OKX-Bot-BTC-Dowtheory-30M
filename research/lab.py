"""Strategy research lab — hunts for NEW entry ideas (different from the
DowTheoryBreak bot) on real OKX BTC-USDT-SWAP data across timeframes.

Constraints (fixed by the research brief):
    * RR 1:1  (TP distance == SL distance)
    * SL/TP distance >= 500 price units
    * target: winrate >= 70%

Resolution is PESSIMISTIC: a bar that touches both TP and SL counts as a
loss, so reported winrates are conservative floors.  Top candidates can be
re-resolved with real 1m intrabar data (``refine``).

Usage:
    python -m research.lab fetch            # download & cache candles
    python -m research.lab run              # run the strategy grid
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import load_config
from bot.engine import Candle, ltf_first_hit
from bot.okx_client import OKXClient
from bot import data as datamod

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
INST = "BTC-USDT-SWAP"

# timeframe -> bars to fetch (approx. coverage in days at 100%-uptime)
TF_BARS = {
    "15m": 15000,   # ~156 d
    "30m": 13000,   # ~270 d
    "1H": 9000,     # ~375 d
    "2H": 4500,     # ~375 d
    "4H": 2500,     # ~416 d
}
DISTS = [500.0, 750.0, 1000.0, 1500.0, 2000.0]
MIN_TRADES = 30


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def _cache_path(tf: str) -> str:
    return os.path.join(DATA_DIR, f"{INST}_{tf}.json")


def fetch_all(client: OKXClient) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    for tf, n in TF_BARS.items():
        path = _cache_path(tf)
        if os.path.exists(path):
            print(f"{tf}: cache exists, skipping")
            continue
        print(f"Fetching {n} bars of {tf} ...")
        candles = datamod.fetch_history(client, INST, tf, n)
        with open(path, "w") as fh:
            json.dump([[c.ts, c.open, c.high, c.low, c.close, c.volume] for c in candles], fh)
        print(f"{tf}: saved {len(candles)} bars "
              f"({_ts(candles[0].ts)} .. {_ts(candles[-1].ts)})")


def load_candles(tf: str) -> List[Candle]:
    with open(_cache_path(tf)) as fh:
        rows = json.load(fh)
    return [Candle(ts=r[0], open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in rows]


def _ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# Indicators (list-based, NaN-padded)
# --------------------------------------------------------------------------
NAN = float("nan")


def rsi_series(closes: List[float], period: int) -> List[float]:
    out = [NAN] * len(closes)
    avg_g = avg_l = 0.0
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        g, l = max(ch, 0.0), max(-ch, 0.0)
        if i <= period:
            avg_g += g / period
            avg_l += l / period
            if i == period:
                out[i] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
        else:
            avg_g = (avg_g * (period - 1) + g) / period
            avg_l = (avg_l * (period - 1) + l) / period
            out[i] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return out


def ema_series(vals: List[float], period: int) -> List[float]:
    out = [NAN] * len(vals)
    k = 2.0 / (period + 1)
    e = None
    for i, v in enumerate(vals):
        e = v if e is None else v * k + e * (1 - k)
        if i >= period - 1:
            out[i] = e
    return out


def sma_std(vals: List[float], period: int) -> Tuple[List[float], List[float]]:
    means = [NAN] * len(vals)
    stds = [NAN] * len(vals)
    s = s2 = 0.0
    for i, v in enumerate(vals):
        s += v
        s2 += v * v
        if i >= period:
            old = vals[i - period]
            s -= old
            s2 -= old * old
        if i >= period - 1:
            m = s / period
            var = max(s2 / period - m * m, 0.0)
            means[i] = m
            stds[i] = math.sqrt(var)
    return means, stds


def atr_simple(candles: List[Candle], period: int = 14) -> List[float]:
    out = [NAN] * len(candles)
    a = None
    for i, c in enumerate(candles):
        tr = c.high - c.low if i == 0 else max(
            c.high - c.low, abs(c.high - candles[i - 1].close), abs(c.low - candles[i - 1].close))
        a = tr if a is None else (a * (period - 1) + tr) / period
        if i >= period:
            out[i] = a
    return out


def stoch_k(candles: List[Candle], period: int = 14) -> List[float]:
    out = [NAN] * len(candles)
    for i in range(period - 1, len(candles)):
        hi = max(c.high for c in candles[i - period + 1:i + 1])
        lo = min(c.low for c in candles[i - period + 1:i + 1])
        out[i] = 50.0 if hi == lo else (candles[i].close - lo) / (hi - lo) * 100
    return out


# --------------------------------------------------------------------------
# Backtester — RR 1:1, market entry at next bar open, pessimistic ambiguity
# --------------------------------------------------------------------------
@dataclass
class Trade:
    dir: int          # +1 long, -1 short
    entry: float
    sl: float
    tp: float
    entry_bar: int
    close_bar: int
    win: bool
    ambiguous: bool   # both TP & SL touched on the closing bar


@dataclass
class Result:
    name: str
    tf: str
    dist: float
    trades: List[Trade]

    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.win)

    @property
    def winrate(self) -> float:
        return self.wins / self.n * 100 if self.n else 0.0

    @property
    def net_r(self) -> float:
        return self.wins - (self.n - self.wins)

    @property
    def n_ambiguous(self) -> int:
        return sum(1 for t in self.trades if t.ambiguous)


SignalFn = Callable[[List[Candle], Dict], List[Tuple[int, int]]]


def run_bt(candles: List[Candle], signals: List[Tuple[int, int]], dist: float) -> List[Trade]:
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
                win = hit_tp and not hit_sl          # both -> pessimistic loss
                trades.append(Trade(d, e, sl, tp, b, i, win, hit_sl and hit_tp))
                open_tr = None
        if not was_open and i > 0 and (i - 1) in sig:
            d = sig[i - 1]
            e = c.open
            sl, tp = e - d * dist, e + d * dist
            hit_sl = (c.low <= sl) if d > 0 else (c.high >= sl)
            hit_tp = (c.high >= tp) if d > 0 else (c.low <= tp)
            if hit_sl or hit_tp:
                win = hit_tp and not hit_sl
                trades.append(Trade(d, e, sl, tp, i, i, win, hit_sl and hit_tp))
            else:
                open_tr = (d, e, sl, tp, i)
    return trades


# --------------------------------------------------------------------------
# Strategy generators — every entry style is deliberately DIFFERENT from the
# bot's Dow pattern break / pullback / mid-level entries.
# --------------------------------------------------------------------------
def strategies(candles: List[Candle]) -> Dict[str, List[Tuple[int, int]]]:
    closes = [c.close for c in candles]
    n = len(candles)
    atr = atr_simple(candles, 14)
    out: Dict[str, List[Tuple[int, int]]] = {}

    # 1) RSI threshold reversal (long when oversold, short when overbought)
    for period in (7, 14):
        r = rsi_series(closes, period)
        for os_, ob in ((30, 70), (25, 75), (20, 80)):
            sigs = []
            for i in range(n):
                if r[i] == r[i]:
                    if r[i] < os_:
                        sigs.append((i, 1))
                    elif r[i] > ob:
                        sigs.append((i, -1))
            out[f"rsi{period}_rev_{os_}/{ob}"] = sigs
            # cross-back variant: fire only when RSI re-enters the band
            sigs2 = []
            for i in range(1, n):
                if r[i] == r[i] and r[i - 1] == r[i - 1]:
                    if r[i - 1] < os_ <= r[i]:
                        sigs2.append((i, 1))
                    elif r[i - 1] > ob >= r[i]:
                        sigs2.append((i, -1))
            out[f"rsi{period}_xback_{os_}/{ob}"] = sigs2

    # 2) Bollinger-band reversion
    mean20, std20 = sma_std(closes, 20)
    for k in (2.0, 2.5, 3.0):
        sigs = []
        for i in range(n):
            if mean20[i] == mean20[i]:
                if closes[i] < mean20[i] - k * std20[i]:
                    sigs.append((i, 1))
                elif closes[i] > mean20[i] + k * std20[i]:
                    sigs.append((i, -1))
        out[f"boll20_rev_k{k}"] = sigs

    # 3) N consecutive closes reversal
    for streak in (3, 4, 5, 6):
        sigs = []
        run = 0
        for i in range(1, n):
            if closes[i] < closes[i - 1]:
                run = run - 1 if run < 0 else -1
            elif closes[i] > closes[i - 1]:
                run = run + 1 if run > 0 else 1
            else:
                run = 0
            if run <= -streak:
                sigs.append((i, 1))
            elif run >= streak:
                sigs.append((i, -1))
        out[f"consec{streak}_rev"] = sigs

    # 4) Big-candle fade (contrarian on a range > k*ATR candle)
    for mult in (2.0, 2.5, 3.0):
        sigs = []
        for i in range(n):
            if atr[i] == atr[i] and (candles[i].high - candles[i].low) > mult * atr[i]:
                sigs.append((i, 1 if closes[i] < candles[i].open else -1))
        out[f"bigbar_fade_{mult}xATR"] = sigs

    # 5) EMA cross trend-following
    for fast, slow in ((9, 21), (20, 50), (50, 200)):
        ef, es = ema_series(closes, fast), ema_series(closes, slow)
        sigs = []
        for i in range(1, n):
            if es[i] == es[i] and es[i - 1] == es[i - 1]:
                if ef[i - 1] <= es[i - 1] and ef[i] > es[i]:
                    sigs.append((i, 1))
                elif ef[i - 1] >= es[i - 1] and ef[i] < es[i]:
                    sigs.append((i, -1))
        out[f"emax_{fast}/{slow}"] = sigs

    # 6) Stochastic %K reversal
    k14 = stoch_k(candles, 14)
    for lo, hi in ((20, 80), (10, 90)):
        sigs = []
        for i in range(n):
            if k14[i] == k14[i]:
                if k14[i] < lo:
                    sigs.append((i, 1))
                elif k14[i] > hi:
                    sigs.append((i, -1))
        out[f"stoch14_rev_{lo}/{hi}"] = sigs

    # 7) Funding-hour entries (OKX funding 00/08/16 UTC): enter at that open
    for hour in (0, 8, 16):
        for d, tag in ((1, "long"), (-1, "short")):
            sigs = []
            for i in range(n - 1):
                nxt = datetime.fromtimestamp(candles[i + 1].ts / 1000, tz=timezone.utc)
                if nxt.hour == hour and nxt.minute == 0:
                    sigs.append((i, d))
            out[f"fund{hour:02d}_{tag}"] = sigs

    # 8) Pin-bar (wick rejection)
    sigs = []
    for i, c in enumerate(candles):
        rng = c.high - c.low
        if rng <= 0:
            continue
        body = abs(c.close - c.open)
        lower = min(c.open, c.close) - c.low
        upper = c.high - max(c.open, c.close)
        if lower >= 2 * body and lower >= 0.6 * rng:
            sigs.append((i, 1))
        elif upper >= 2 * body and upper >= 0.6 * rng:
            sigs.append((i, -1))
    out["pinbar_rev"] = sigs

    return out


# --------------------------------------------------------------------------
# Grid runner / refinement
# --------------------------------------------------------------------------
def run_grid(tfs: Optional[List[str]] = None) -> List[Result]:
    results: List[Result] = []
    for tf in (tfs or TF_BARS):
        candles = load_candles(tf)
        sigs = strategies(candles)
        for name, s in sigs.items():
            for dist in DISTS:
                trades = run_bt(candles, s, dist)
                results.append(Result(name=name, tf=tf, dist=dist, trades=trades))
        print(f"{tf}: {len(candles)} bars, {len(sigs)} strategies done "
              f"({_ts(candles[0].ts)} .. {_ts(candles[-1].ts)})")
    return results


def refine_with_1m(client: OKXClient, res: Result, tf: str) -> Tuple[int, int]:
    """Re-resolve ambiguous (both-touched) bars with real 1m data.

    Market entry at bar open means the position exists from the first
    sub-bar, so plain first-hit ordering applies.  Returns
    (flipped_to_win, still_loss)."""
    candles = load_candles(tf)
    provider = datamod.LtfProvider(client, INST, tf, "1m")
    flipped = kept = 0
    for t in res.trades:
        if not t.ambiguous or t.win:
            continue
        sub = provider(candles[t.close_bar].ts)
        if sub and ltf_first_hit(sub, t.dir > 0, t.sl, t.tp) == 2:
            t.win = True
            flipped += 1
        else:
            kept += 1
    return flipped, kept


def leaderboard(results: List[Result], top: int = 25, min_trades: int = MIN_TRADES) -> str:
    ok = [r for r in results if r.n >= min_trades]
    ok.sort(key=lambda r: (-r.winrate, -r.n))
    lines = [f"{'strategy':28s} {'tf':>4s} {'dist':>6s} {'trades':>6s} "
             f"{'win%':>6s} {'netR':>6s} {'ambig':>5s}"]
    for r in ok[:top]:
        lines.append(f"{r.name:28s} {r.tf:>4s} {r.dist:>6.0f} {r.n:>6d} "
                     f"{r.winrate:>6.1f} {r.net_r:>+6.0f} {r.n_ambiguous:>5d}")
    return "\n".join(lines)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "fetch":
        cfg = load_config("config.yaml")
        client = OKXClient(demo=cfg.exchange.demo, base_url=cfg.exchange.base_url)
        fetch_all(client)
    elif cmd == "run":
        results = run_grid()
        print()
        print(leaderboard(results))
        hits = [r for r in results if r.n >= MIN_TRADES and r.winrate >= 70.0]
        print(f"\n>=70% winrate candidates (>= {MIN_TRADES} trades): {len(hits)}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
