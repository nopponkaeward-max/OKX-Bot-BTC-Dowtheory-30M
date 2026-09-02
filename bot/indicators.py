"""Technical primitives used by the strategy: pivots and ATR.

These mirror the Pine Script built-ins ``ta.pivothigh`` / ``ta.pivotlow`` and
``ta.atr`` closely enough to reproduce the indicator's signals bar-for-bar.
"""

from __future__ import annotations

from typing import List, Optional


def pivot_high(highs: List[float], center: int, left: int, right: int) -> Optional[float]:
    """Return ``highs[center]`` if it is a pivot high, else ``None``.

    A pivot high requires the center bar to be strictly greater than every bar
    within ``left`` bars to its left and ``right`` bars to its right — the same
    definition used by ``ta.pivothigh(high, left, right)`` in Pine.  The pivot
    is only *confirmable* once ``right`` bars have printed after it.
    """
    if center - left < 0 or center + right >= len(highs):
        return None
    v = highs[center]
    for j in range(center - left, center):
        if highs[j] >= v:
            return None
    for j in range(center + 1, center + right + 1):
        if highs[j] >= v:
            return None
    return v


def pivot_low(lows: List[float], center: int, left: int, right: int) -> Optional[float]:
    """Return ``lows[center]`` if it is a pivot low, else ``None``."""
    if center - left < 0 or center + right >= len(lows):
        return None
    v = lows[center]
    for j in range(center - left, center):
        if lows[j] <= v:
            return None
    for j in range(center + 1, center + right + 1):
        if lows[j] <= v:
            return None
    return v


def true_range(high: float, low: float, prev_close: Optional[float]) -> float:
    if prev_close is None:
        return high - low
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr_series(highs: List[float], lows: List[float], closes: List[float], period: int) -> List[float]:
    """Wilder's ATR (RMA of True Range), matching Pine ``ta.atr(period)``.

    Returns a list the same length as the inputs; leading values (before the
    average is seeded) are filled with the running simple average of TR.
    """
    n = len(closes)
    out: List[float] = [float("nan")] * n
    if n == 0:
        return out
    trs: List[float] = []
    for i in range(n):
        pc = closes[i - 1] if i > 0 else None
        trs.append(true_range(highs[i], lows[i], pc))
    # Pine's ta.rma seeds with an SMA over the first `period` values, then
    # applies the recursive RMA: rma = (prev*(p-1) + tr)/p.
    rma: Optional[float] = None
    for i in range(n):
        if i + 1 < period:
            out[i] = sum(trs[: i + 1]) / (i + 1)  # provisional average
        elif i + 1 == period:
            rma = sum(trs[:period]) / period
            out[i] = rma
        else:
            rma = (rma * (period - 1) + trs[i]) / period  # type: ignore[operator]
            out[i] = rma
    return out
