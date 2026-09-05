"""Technical indicators: Wilder ATR."""

from __future__ import annotations
from typing import List, Optional


def true_range(high: float, low: float, prev_close: Optional[float]) -> float:
    if prev_close is None:
        return high - low
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr_series(highs: List[float], lows: List[float], closes: List[float],
               period: int) -> List[float]:
    """Wilder's ATR (RMA of True Range), matching Pine ``ta.atr(period)``."""
    n = len(closes)
    out: List[float] = [float("nan")] * n
    if n == 0:
        return out
    trs: List[float] = []
    for i in range(n):
        pc = closes[i - 1] if i > 0 else None
        trs.append(true_range(highs[i], lows[i], pc))
    rma: Optional[float] = None
    for i in range(n):
        if i + 1 < period:
            out[i] = sum(trs[: i + 1]) / (i + 1)
        elif i + 1 == period:
            rma = sum(trs[:period]) / period
            out[i] = rma
        else:
            rma = (rma * (period - 1) + trs[i]) / period  # type: ignore[operator]
            out[i] = rma
    return out
