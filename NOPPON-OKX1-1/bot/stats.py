"""Statistics: overall, by-day, monthly — matching Pine on-chart tables."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Dict, List

from .engine import ClosedTrade

DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_SHORT = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _local(ts_ms: int, tz_offset: int) -> datetime:
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc) + timedelta(hours=tz_offset)


def _dow_index(ts_ms: int, tz_offset: int) -> int:
    return _local(ts_ms, tz_offset).weekday()  # 0=Mon..6=Sun


def overall(trades: List[ClosedTrade]) -> Dict:
    wins = [t for t in trades if t.is_win]
    losses = [t for t in trades if not t.is_win]
    total = len(trades)
    net_r = sum(t.r for t in trades)
    wr = (len(wins) / total * 100.0) if total else None

    ordered = sorted(trades, key=lambda t: t.close_ts)
    streak = 0
    max_w = 0
    max_l = 0
    for t in ordered:
        if t.is_win:
            streak = streak + 1 if streak >= 0 else 1
            max_w = max(max_w, streak)
        else:
            streak = streak - 1 if streak <= 0 else -1
            max_l = max(max_l, -streak)

    main_trades = [t for t in trades if not t.is_2nd and not t.is_addon]
    second_trades = [t for t in trades if t.is_2nd and not t.is_addon]
    addon_trades = [t for t in trades if t.is_addon]
    ses_close = [t for t in trades if t.close_reason == "session_close"]

    return {
        "trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "winrate": wr,
        "net_r": net_r,
        "max_win_streak": max_w,
        "max_loss_streak": max_l,
        "current_streak": streak,
        "main": len(main_trades),
        "second": len(second_trades),
        "addon": len(addon_trades),
        "session_close": len(ses_close),
    }


def by_day(trades: List[ClosedTrade], tz_offset: int = 0) -> List[Dict]:
    rows = []
    for d in range(7):
        sub = [t for t in trades if _dow_index(t.origin_ts, tz_offset) == d]
        w = sum(1 for t in sub if t.is_win)
        l = len(sub) - w
        rows.append({
            "day": DAY_LABELS[d],
            "wins": w, "losses": l,
            "winrate": (w / len(sub) * 100.0) if sub else None,
            "net_r": sum(t.r for t in sub),
        })
    return rows


def by_month(trades: List[ClosedTrade], tz_offset: int = 0,
             months: int = 8) -> List[Dict]:
    buckets: Dict[str, List[ClosedTrade]] = {}
    for t in trades:
        dt = _local(t.origin_ts, tz_offset)
        key = f"{dt.year:04d}-{dt.month:02d}"
        buckets.setdefault(key, []).append(t)
    rows = []
    for key in sorted(buckets)[-months:]:
        sub = buckets[key]
        w = sum(1 for t in sub if t.is_win)
        l = len(sub) - w
        y, m = key.split("-")
        rows.append({
            "month": f"{MONTH_SHORT[int(m)]} {y}",
            "wins": w, "losses": l,
            "winrate": (w / len(sub) * 100.0) if sub else None,
            "net_r": sum(t.r for t in sub),
        })
    return rows


def _wr_str(wr) -> str:
    return "-" if wr is None else f"{wr:.1f}%"


def render(trades: List[ClosedTrade], tz_offset: int = 0,
           months: int = 8) -> str:
    o = overall(trades)
    lines: List[str] = []
    lines.append("=" * 50)
    lines.append("  SESSION BREAKOUT — PERFORMANCE")
    lines.append("=" * 50)
    nr = f"{o['net_r']:+.2f}R" if o["trades"] else "-"
    lines.append(f"  Trades   : {o['wins']}W · {o['losses']}L  ({o['trades']})")
    lines.append(f"  Winrate  : {_wr_str(o['winrate'])}")
    lines.append(f"  Net R    : {nr}")
    lines.append(f"  Max Strk : W{o['max_win_streak']} · L{o['max_loss_streak']}")
    cs = o["current_streak"]
    cur = f"W{cs}" if cs > 0 else (f"L{-cs}" if cs < 0 else "-")
    lines.append(f"  Streak   : {cur}")
    lines.append(f"  Order-1: {o['main']}  Order-2: {o['addon']}  Order-3: {o['second']}  SesClose: {o['session_close']}")
    lines.append("-" * 50)
    lines.append("  BY DAY        W-L        WR      NET R")
    for r in by_day(trades, tz_offset):
        wl = f"{r['wins']}W·{r['losses']}L"
        net = f"{r['net_r']:+.2f}R" if (r["wins"] + r["losses"]) else "-"
        lines.append(f"  {r['day']:<5} {wl:>10} {_wr_str(r['winrate']):>8} {net:>10}")
    lines.append("-" * 50)
    lines.append("  MONTHLY       W-L        WR      NET R")
    for r in by_month(trades, tz_offset, months):
        wl = f"{r['wins']}W·{r['losses']}L"
        net = f"{r['net_r']:+.2f}R" if (r["wins"] + r["losses"]) else "-"
        lines.append(f"  {r['month']:<9} {wl:>7} {_wr_str(r['winrate']):>8} {net:>10}")
    lines.append("=" * 50)
    return "\n".join(lines)
