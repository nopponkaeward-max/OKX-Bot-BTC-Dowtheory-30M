"""Candle fetching / parsing helpers."""

from __future__ import annotations

import time
from typing import List

from .engine import Candle
from .okx_client import OKXClient


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
        raw = client._request(  # paginate using 'after' cursor
            "GET", "/api/v5/market/history-candles",
            params={"instId": inst_id, "bar": bar, "limit": 300, "after": oldest})
    collected.sort(key=lambda c: c.ts)
    return collected[-total:] if total else collected
