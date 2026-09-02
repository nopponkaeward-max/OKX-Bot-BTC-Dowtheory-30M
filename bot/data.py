"""Candle fetching / parsing helpers."""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from .engine import Candle
from .okx_client import OKXClient


_BAR_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1H": 3600, "2H": 7200, "4H": 14400,
    "6H": 21600, "12H": 43200, "1D": 86400, "1W": 604800,
}


def bar_to_seconds(bar: str) -> int:
    """Convert an OKX bar string (e.g. "30m", "1H") to its length in seconds."""
    if bar in _BAR_SECONDS:
        return _BAR_SECONDS[bar]
    unit = bar[-1]
    n = int(bar[:-1])
    mult = {"m": 60, "H": 3600, "D": 86400, "W": 604800}.get(unit)
    if mult is None:
        raise ValueError(f"Unrecognized bar timeframe: {bar!r}")
    return n * mult


def parse_okx_candles(raw: List[List[str]], only_confirmed: bool = True) -> List[Candle]:
    """Convert OKX candle rows (newest-first) to oldest-first Candle list.

    OKX row: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
    ``confirm == "1"`` marks a closed bar.
    """
    out: List[Candle] = []
    for row in raw:
        confirm = row[8] if len(row) > 8 else "1"
        if only_confirmed and confirm != "1":
            continue
        out.append(Candle(
            ts=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]) if row[5] not in ("", None) else 0.0,
        ))
    out.sort(key=lambda c: c.ts)
    return out


def fetch_recent(client: OKXClient, inst_id: str, bar: str, limit: int,
                 only_confirmed: bool = True) -> List[Candle]:
    raw = client.get_candles(inst_id, bar=bar, limit=limit)
    return parse_okx_candles(raw, only_confirmed=only_confirmed)


def fetch_history(client: OKXClient, inst_id: str, bar: str, total: int) -> List[Candle]:
    """Page backwards through history-candles to gather ``total`` closed bars."""
    collected: List[Candle] = []
    seen = set()
    raw = client.get_candles(inst_id, bar=bar, limit=300, history=True)
    while raw:
        batch = parse_okx_candles(raw, only_confirmed=True)
        new = [c for c in batch if c.ts not in seen]
        for c in new:
            seen.add(c.ts)
        collected.extend(new)
        if len(collected) >= total or not new:
            break
        oldest = min(c.ts for c in batch)
        time.sleep(0.2)
        raw = client.get_candles(inst_id, bar=bar, limit=300, history=True, after=oldest)
    collected.sort(key=lambda c: c.ts)
    return collected[-total:] if total else collected


# --------------------------------------------------------------------------
# Lower-timeframe (intrabar) sub-candles — mirrors Pine's
# request.security_lower_tf, used to disambiguate same-bar TP/SL touches.
# --------------------------------------------------------------------------
def fetch_subbars(client: OKXClient, inst_id: str, ltf_bar: str,
                  parent_ts_ms: int, parent_bar_seconds: int) -> List[Tuple[float, float]]:
    """Return ascending (high, low) tuples for the sub-bars inside one parent bar.

    Window is ``[parent_ts_ms, parent_ts_ms + parent_bar_seconds*1000)``.
    """
    upper = parent_ts_ms + parent_bar_seconds * 1000
    raw = client.get_candles(inst_id, bar=ltf_bar, limit=100, history=True, after=upper)
    candles = parse_okx_candles(raw, only_confirmed=True)
    window = [c for c in candles if parent_ts_ms <= c.ts < upper]
    window.sort(key=lambda c: c.ts)
    return [(c.high, c.low) for c in window]


class LtfProvider:
    """Callable ``(parent_ts_ms) -> [(high, low), ...] | None`` with caching.

    Pass an instance as ``StrategyEngine(..., ltf_provider=...)`` to enable
    Pine-faithful intrabar TP/SL sequencing. Returns ``None`` (pessimistic
    fallback, same as Pine when no intrabar data exists) on any fetch error.
    """

    def __init__(self, client: OKXClient, inst_id: str, main_bar: str, ltf_bar: str = "1m"):
        self.client = client
        self.inst_id = inst_id
        self.parent_seconds = bar_to_seconds(main_bar)
        self.ltf_bar = ltf_bar
        self._cache: Dict[int, Optional[List[Tuple[float, float]]]] = {}

    def __call__(self, parent_ts_ms: int) -> Optional[List[Tuple[float, float]]]:
        if parent_ts_ms in self._cache:
            return self._cache[parent_ts_ms]
        try:
            sub = fetch_subbars(self.client, self.inst_id, self.ltf_bar,
                                parent_ts_ms, self.parent_seconds)
            result = sub if sub else None
        except Exception:  # noqa: BLE001 — any API hiccup -> pessimistic fallback
            result = None
        self._cache[parent_ts_ms] = result
        return result
