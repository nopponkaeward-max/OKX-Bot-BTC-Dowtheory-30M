"""Tests for the Session Breakout strategy engine."""

from __future__ import annotations

import math
import pytest
from bot.config import Config, StrategyConfig, SessionDef
from bot.engine import (
    Candle, StrategyEngine, _parse_ses_time, _bar_in_session,
    _is_dst, _day_of_week, one_r_dist_of,
)
from bot.indicators import true_range, atr_series


# ---- helpers --------------------------------------------------------

def _ts(year=2025, month=1, day=6, hour=0, minute=0):
    """UTC timestamp in ms (2025-01-06 = Monday)."""
    from datetime import datetime, timezone
    dt = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _cfg(**overrides) -> Config:
    cfg = Config()
    cfg.strategy.sessions = [
        SessionDef("Sydney", True, "2000-0500", "2100-0600"),
    ]
    for k, v in overrides.items():
        if hasattr(cfg.strategy, k):
            setattr(cfg.strategy, k, v)
    cfg.exchange.bar = "30m"
    return cfg


def _candle(ts, o, h, l, c):
    return Candle(ts=ts, o=o, h=h, l=l, c=c)


# ---- time helpers ---------------------------------------------------

class TestParseTime:
    def test_normal(self):
        assert _parse_ses_time("2000-0500") == (20 * 60, 5 * 60)

    def test_same_day(self):
        assert _parse_ses_time("0800-1700") == (8 * 60, 17 * 60)


class TestBarInSession:
    def test_inside(self):
        ts = _ts(hour=21, minute=0)
        assert _bar_in_session(ts, 30, 20 * 60, 5 * 60) is True

    def test_outside(self):
        ts = _ts(hour=10, minute=0)
        assert _bar_in_session(ts, 30, 20 * 60, 5 * 60) is False

    def test_on_start_edge(self):
        ts = _ts(hour=20, minute=0)
        assert _bar_in_session(ts, 30, 20 * 60, 5 * 60) is True

    def test_cross_midnight(self):
        ts = _ts(hour=2, minute=0)
        assert _bar_in_session(ts, 30, 20 * 60, 5 * 60) is True


class TestDST:
    def test_winter(self):
        assert _is_dst(_ts(month=1)) is False

    def test_summer(self):
        assert _is_dst(_ts(month=6)) is True

    def test_april_boundary(self):
        assert _is_dst(_ts(month=4)) is True

    def test_october_boundary(self):
        assert _is_dst(_ts(month=10)) is False


class TestDayOfWeek:
    def test_monday(self):
        assert _day_of_week(_ts(day=6)) == 0  # 2025-01-06 = Mon

    def test_friday(self):
        assert _day_of_week(_ts(day=10)) == 4  # Fri


# ---- indicators -----------------------------------------------------

class TestTrueRange:
    def test_no_prev(self):
        assert true_range(110, 90, None) == 20

    def test_with_prev(self):
        assert true_range(110, 90, 105) == 20

    def test_gap_up(self):
        assert true_range(120, 110, 100) == 20  # |120-100|=20


class TestATR:
    def test_short_series(self):
        h = [10, 12, 11]
        l = [8, 9, 9]
        c = [9, 11, 10]
        result = atr_series(h, l, c, 3)
        assert len(result) == 3
        assert not math.isnan(result[2])


# ---- 1R distance ----------------------------------------------------

class TestOneR:
    def test_sl_pct(self):
        cfg = StrategyConfig(one_r_basis="SL%", one_r_pct_val=50.0)
        assert one_r_dist_of(cfg, 100.0) == 50.0

    def test_distance(self):
        cfg = StrategyConfig(one_r_basis="Distance", one_r_dist_fix=5.0)
        assert one_r_dist_of(cfg, 100.0) == 5.0

    def test_atr(self):
        cfg = StrategyConfig(one_r_basis="ATR", one_r_atr_mult=1.5)
        assert one_r_dist_of(cfg, 100.0, atr_val=10.0) == 15.0


# ---- session detection + plan creation ------------------------------

class TestSessionDetection:
    def test_session_creates_plans(self):
        cfg = _cfg(entry_mode="Breakout")
        eng = StrategyEngine(cfg)

        # Bars inside Sydney session (20:00-05:00 UTC, winter)
        bars = []
        for h in range(20, 24):
            for m in (0, 30):
                bars.append(_candle(_ts(hour=h, minute=m),
                                    100, 105, 95, 100))
        for h in range(0, 5):
            for m in (0, 30):
                bars.append(_candle(_ts(day=7, hour=h, minute=m),
                                    100, 110, 90, 100))
        # Bar outside session → session end
        bars.append(_candle(_ts(day=7, hour=5, minute=0),
                            100, 102, 98, 100))

        events = []
        for b in bars:
            events.extend(eng.on_bar(b))

        plan_events = [e for e in events if e["type"] == "PLAN_CREATED"]
        assert len(plan_events) == 1
        assert plan_events[0]["session"] == "Sydney"
        assert len(eng.plans) == 2  # buy + sell

    def test_trade_day_filter(self):
        cfg = _cfg(entry_mode="Breakout",
                   trade_days={"sun": False, "mon": False, "tue": True,
                               "wed": True, "thu": True, "fri": True,
                               "sat": False})
        eng = StrategyEngine(cfg)

        # Monday session end
        bars = []
        for h in range(20, 24):
            for m in (0, 30):
                bars.append(_candle(_ts(hour=h, minute=m), 100, 105, 95, 100))
        for h in range(0, 5):
            for m in (0, 30):
                bars.append(_candle(_ts(day=7, hour=h, minute=m),
                                    100, 110, 90, 100))
        bars.append(_candle(_ts(day=7, hour=5, minute=0), 100, 102, 98, 100))

        events = []
        for b in bars:
            events.extend(eng.on_bar(b))

        plan_events = [e for e in events if e["type"] == "PLAN_CREATED"]
        assert len(plan_events) == 0  # Monday disabled


# ---- breakout entry -------------------------------------------------

class TestBreakoutEntry:
    def _run_session_and_breakout(self, entry_mode="Breakout"):
        cfg = _cfg(entry_mode=entry_mode, one_r_basis="SL%",
                   one_r_pct_val=50.0, rr_ratio=2.0, spread_pts=0.0)
        eng = StrategyEngine(cfg)

        # Build Sydney session with hi=110, lo=90
        for h in range(20, 24):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(hour=h, minute=m), 100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=0, minute=0), 100, 110, 90, 100))
        for h in range(1, 5):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(day=7, hour=h, minute=m),
                                   100, 100, 100, 100))
        # Session end
        eng.on_bar(_candle(_ts(day=7, hour=5, minute=0), 100, 100, 100, 100))
        assert len(eng.plans) == 2
        return cfg, eng

    def test_breakout_buy_fill(self):
        _, eng = self._run_session_and_breakout("Breakout")
        events = eng.on_bar(_candle(_ts(day=7, hour=5, minute=30),
                                     100, 115, 100, 112))
        fills = [e for e in events if e["type"] == "FILL"]
        assert len(fills) == 1
        assert fills[0]["is_buy"] is True
        assert len(eng.plans) == 0  # OCO partner cancelled

    def test_breakout_sell_fill(self):
        _, eng = self._run_session_and_breakout("Breakout")
        events = eng.on_bar(_candle(_ts(day=7, hour=5, minute=30),
                                     100, 100, 85, 88))
        fills = [e for e in events if e["type"] == "FILL"]
        assert len(fills) == 1
        assert fills[0]["is_buy"] is False


# ---- pullback entry -------------------------------------------------

class TestPullbackEntry:
    def test_pullback_flow(self):
        cfg = _cfg(entry_mode="Pullback", pullback_range_pct=20.0,
                   one_r_basis="SL%", one_r_pct_val=50.0, rr_ratio=2.0)
        eng = StrategyEngine(cfg)

        # Session with hi=110, lo=90 (range=20)
        for h in range(20, 24):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(hour=h, minute=m), 100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=0, minute=0), 100, 110, 90, 100))
        for h in range(1, 5):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(day=7, hour=h, minute=m),
                                   100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=5, minute=0), 100, 100, 100, 100))
        assert len(eng.plans) == 2

        # Break buy edge: h > 110
        eng.on_bar(_candle(_ts(day=7, hour=5, minute=30), 110, 115, 110, 112))
        buy_plans = [p for p in eng.plans if p.is_buy]
        assert buy_plans[0].state == 1  # waiting pullback

        # Pullback: range=20, 20% = 4pts, pb_price = 110-4 = 106
        events = eng.on_bar(_candle(_ts(day=7, hour=6, minute=0),
                                     108, 108, 105, 106))
        fills = [e for e in events if e["type"] == "FILL"]
        assert len(fills) == 1
        assert fills[0]["is_buy"] is True


# ---- TP/SL resolution -----------------------------------------------

class TestTPSL:
    def _setup_with_fill(self, **kw):
        cfg = _cfg(entry_mode="Breakout", one_r_basis="SL%",
                   one_r_pct_val=50.0, rr_ratio=2.0, spread_pts=0.0, **kw)
        eng = StrategyEngine(cfg)

        for h in range(20, 24):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(hour=h, minute=m), 100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=0, minute=0), 100, 110, 90, 100))
        for h in range(1, 5):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(day=7, hour=h, minute=m),
                                   100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=5, minute=0), 100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=5, minute=30), 100, 115, 100, 112))
        assert len(eng.trades) == 1
        return cfg, eng

    def test_tp_hit(self):
        _, eng = self._setup_with_fill()
        t = eng.trades[0]
        events = eng.on_bar(_candle(_ts(day=7, hour=6, minute=0),
                                     t.entry, t.tp + 1, t.entry, t.tp))
        closed = [e for e in events if e["type"] == "TRADE_CLOSED"]
        assert len(closed) == 1
        assert closed[0]["is_win"] is True

    def test_sl_hit(self):
        _, eng = self._setup_with_fill()
        t = eng.trades[0]
        events = eng.on_bar(_candle(_ts(day=7, hour=6, minute=0),
                                     t.entry, t.entry, t.sl - 1, t.sl))
        closed = [e for e in events if e["type"] == "TRADE_CLOSED"]
        assert len(closed) == 1
        assert closed[0]["is_win"] is False


# ---- 2nd order rescue -----------------------------------------------

class TestSecondOrder:
    def test_2nd_order_on_sl(self):
        cfg = _cfg(entry_mode="Breakout", one_r_basis="SL%",
                   one_r_pct_val=50.0, rr_ratio=2.0,
                   use_2nd_order=True, use_addon_50=False)
        eng = StrategyEngine(cfg)

        for h in range(20, 24):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(hour=h, minute=m), 100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=0, minute=0), 100, 110, 90, 100))
        for h in range(1, 5):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(day=7, hour=h, minute=m),
                                   100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=5, minute=0), 100, 100, 100, 100))
        # Breakout buy fill
        eng.on_bar(_candle(_ts(day=7, hour=5, minute=30), 100, 115, 100, 112))
        assert len(eng.trades) == 1

        t = eng.trades[0]
        # SL hit → arms 2nd pending
        eng.on_bar(_candle(_ts(day=7, hour=6, minute=0),
                           t.entry, t.entry, t.sl - 1, t.sl))
        assert len(eng.trades) == 0
        assert len(eng.second_pending) == 1

        # Re-break → 2nd order fills
        sp = eng.second_pending[0]
        events = eng.on_bar(_candle(_ts(day=7, hour=6, minute=30),
                                     sp.entry, sp.entry + 5, sp.entry - 1,
                                     sp.entry + 3))
        fills_2nd = [e for e in events if e["type"] == "FILL_2ND"]
        assert len(fills_2nd) == 1


# ---- add-on 50% ----------------------------------------------------

class TestAddon:
    def test_addon_trigger(self):
        cfg = _cfg(entry_mode="Breakout", one_r_basis="SL%",
                   one_r_pct_val=30.0, rr_ratio=2.0,
                   use_addon_50=True, addon_tp_mode="RR", addon_rr=3.0,
                   use_2nd_order=False, sl_edge_mode=True)
        eng = StrategyEngine(cfg)

        # Session: hi=110, lo=90, range=20
        for h in range(20, 24):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(hour=h, minute=m), 100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=0, minute=0), 100, 110, 90, 100))
        for h in range(1, 5):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(day=7, hour=h, minute=m),
                                   100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=5, minute=0), 100, 100, 100, 100))
        # Buy breakout: entry=110, sl_edge_mode → sl=90 (session lo)
        # ao_mid = 110 - 20/2 = 100 → ent(110) > ao_mid(100) and sl(90) <= ao_mid(100) → valid
        eng.on_bar(_candle(_ts(day=7, hour=5, minute=30), 100, 115, 100, 112))
        assert len(eng.trades) == 1
        assert len(eng.addon_pending) == 1

        # 50% level = 100, candle hits it but stays above SL (104)
        ap = eng.addon_pending[0]
        assert ap.level == pytest.approx(100.0)
        events = eng.on_bar(_candle(_ts(day=7, hour=6, minute=0),
                                     105, 105, 99, 104.5))
        addon_fills = [e for e in events if e["type"] == "FILL_ADDON"]
        assert len(addon_fills) == 1
        assert len(eng.trades) == 2


# ---- Order-3 deferred (waits for both Order-1 + Order-2 SL) ----------

class TestOrder3Deferred:
    def test_order3_waits_for_addon_sl(self):
        """Order-3 must NOT arm until both Order-1 and Order-2 hit SL."""
        cfg = _cfg(entry_mode="Breakout", one_r_basis="Distance",
                   one_r_dist_fix=5.0, rr_ratio=2.0,
                   use_2nd_order=True, use_addon_50=True,
                   addon_tp_mode="RR", addon_rr=2.0,
                   sl_edge_mode=True)
        eng = StrategyEngine(cfg)

        # Session: hi=110, lo=90, range=20
        for h in range(20, 24):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(hour=h, minute=m), 100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=0, minute=0), 100, 110, 90, 100))
        for h in range(1, 5):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(day=7, hour=h, minute=m),
                                   100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=5, minute=0), 100, 100, 100, 100))

        # Buy breakout → Order-1 entry=110 sl_edge=90
        eng.on_bar(_candle(_ts(day=7, hour=5, minute=30), 100, 115, 100, 112))
        assert len(eng.trades) == 1
        assert len(eng.addon_pending) == 1

        # Addon triggers at 50% = 100
        # addon entry=100, sl=90 (same edge), addon risk=10
        eng.on_bar(_candle(_ts(day=7, hour=6, minute=0), 105, 105, 99, 104))
        assert len(eng.trades) == 2

        t1 = [t for t in eng.trades if not t.is_addon][0]
        t2 = [t for t in eng.trades if t.is_addon][0]
        # Main SL=90, Addon SL=90 — both same. We need them different.
        # Force addon SL higher so it survives when main SLs
        t2.sl = 93.0

        # Price drops to 89 — only Order-1 SL (90) hit, addon SL (93) also hit
        # Need to hit Order-1 SL but NOT Order-2 SL
        eng.on_bar(_candle(_ts(day=7, hour=6, minute=30),
                           100, 100, 89, 91))
        # Order-1 (SL=90) is hit, Order-2 (SL=93) also hit on same bar
        # Since both pop in same bar, we need separate bars instead.
        # Restart with separate SL scenario:
        pass

        # -- fresh approach: use different SL values --
        cfg2 = _cfg(entry_mode="Breakout", one_r_basis="Distance",
                    one_r_dist_fix=5.0, rr_ratio=4.0,
                    use_2nd_order=True, use_addon_50=True,
                    addon_tp_mode="RR", addon_rr=2.0,
                    sl_edge_mode=True)
        eng2 = StrategyEngine(cfg2)

        for h in range(20, 24):
            for m in (0, 30):
                eng2.on_bar(_candle(_ts(hour=h, minute=m), 100, 100, 100, 100))
        eng2.on_bar(_candle(_ts(day=7, hour=0, minute=0), 100, 110, 90, 100))
        for h in range(1, 5):
            for m in (0, 30):
                eng2.on_bar(_candle(_ts(day=7, hour=h, minute=m),
                                    100, 100, 100, 100))
        eng2.on_bar(_candle(_ts(day=7, hour=5, minute=0), 100, 100, 100, 100))
        eng2.on_bar(_candle(_ts(day=7, hour=5, minute=30), 100, 115, 100, 112))
        assert len(eng2.addon_pending) == 1
        eng2.on_bar(_candle(_ts(day=7, hour=6, minute=0), 105, 105, 99, 104))
        assert len(eng2.trades) == 2

        # Manually set different SL for addon so we can SL them separately
        main_t = [t for t in eng2.trades if not t.is_addon][0]
        addon_t = [t for t in eng2.trades if t.is_addon][0]
        main_t.sl = 95.0    # main SL higher
        addon_t.sl = 85.0   # addon SL lower

        # Bar hits main SL (95) but NOT addon SL (85)
        eng2.on_bar(_candle(_ts(day=7, hour=6, minute=30),
                            100, 100, 94, 96))
        assert len(eng2.second_pending) == 0  # NOT armed
        assert len(eng2.deferred_2nd) == 1    # deferred

        # Bar hits addon SL (85)
        addon_t2 = eng2.trades[0]
        assert addon_t2.is_addon
        eng2.on_bar(_candle(_ts(day=7, hour=7, minute=0),
                            90, 90, 84, 86))
        assert len(eng2.trades) == 0
        assert len(eng2.deferred_2nd) == 0
        assert len(eng2.second_pending) == 1  # Order-3 armed!

    def test_order3_cancelled_if_addon_tp(self):
        """If Order-2 wins TP, deferred Order-3 is cancelled."""
        cfg = _cfg(entry_mode="Breakout", one_r_basis="Distance",
                   one_r_dist_fix=5.0, rr_ratio=4.0,
                   use_2nd_order=True, use_addon_50=True,
                   addon_tp_mode="RR", addon_rr=2.0,
                   sl_edge_mode=True)
        eng = StrategyEngine(cfg)

        for h in range(20, 24):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(hour=h, minute=m), 100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=0, minute=0), 100, 110, 90, 100))
        for h in range(1, 5):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(day=7, hour=h, minute=m),
                                   100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=5, minute=0), 100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=5, minute=30), 100, 115, 100, 112))
        eng.on_bar(_candle(_ts(day=7, hour=6, minute=0), 105, 105, 99, 104))
        assert len(eng.trades) == 2

        # Set different SLs so main can SL without addon
        main_t = [t for t in eng.trades if not t.is_addon][0]
        addon_t = [t for t in eng.trades if t.is_addon][0]
        main_t.sl = 95.0
        addon_t.sl = 85.0

        # Order-1 SL → deferred
        eng.on_bar(_candle(_ts(day=7, hour=6, minute=30),
                           100, 100, 94, 96))
        assert len(eng.deferred_2nd) == 1

        # Order-2 hits TP → deferred cancelled
        t2 = eng.trades[0]
        assert t2.is_addon
        eng.on_bar(_candle(_ts(day=7, hour=7, minute=0),
                           t2.entry, t2.tp + 1, t2.entry, t2.tp))
        assert len(eng.deferred_2nd) == 0
        assert len(eng.second_pending) == 0  # NOT armed


# ---- trailing SL ----------------------------------------------------

class TestTrailing:
    def test_trail_locks(self):
        cfg = _cfg(entry_mode="Breakout", one_r_basis="SL%",
                   one_r_pct_val=50.0, rr_ratio=5.0,
                   use_trail=True, trail_trigger_r=2.0, trail_lock_r=1.0,
                   use_addon_50=False, use_2nd_order=False)
        eng = StrategyEngine(cfg)

        for h in range(20, 24):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(hour=h, minute=m), 100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=0, minute=0), 100, 110, 90, 100))
        for h in range(1, 5):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(day=7, hour=h, minute=m),
                                   100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=5, minute=0), 100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=5, minute=30), 100, 115, 100, 112))
        assert len(eng.trades) == 1

        t = eng.trades[0]
        one_r = t.pips_dist
        trig_px = t.entry + one_r * 2.0
        lock_px = t.entry + one_r * 1.0

        # Trigger trailing — low must stay above the locked SL
        eng.on_bar(_candle(_ts(day=7, hour=6, minute=0),
                           lock_px + 5, trig_px + 1, lock_px + 1, trig_px))
        assert eng.trades[0].trailed is True
        assert eng.trades[0].sl == pytest.approx(lock_px, rel=1e-6)


# ---- close on new session -------------------------------------------

class TestCloseOnNewSession:
    def test_close(self):
        cfg = _cfg(entry_mode="Breakout", close_main_on_new_ses=True,
                   use_addon_50=False, use_2nd_order=False)
        eng = StrategyEngine(cfg)

        # Session 1
        for h in range(20, 24):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(hour=h, minute=m), 100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=0, minute=0), 100, 110, 90, 100))
        for h in range(1, 5):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(day=7, hour=h, minute=m),
                                   100, 100, 100, 100))
        # Session end → plans
        eng.on_bar(_candle(_ts(day=7, hour=5, minute=0), 100, 100, 100, 100))

        # Breakout → fill
        eng.on_bar(_candle(_ts(day=7, hour=5, minute=30), 100, 115, 100, 112))
        assert len(eng.trades) == 1

        # Gap to next session start
        for h in range(6, 20):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(day=7, hour=h, minute=m),
                                   112, 112, 112, 112))

        # Next session start → close
        eng.on_bar(_candle(_ts(day=7, hour=20, minute=0), 112, 112, 112, 112))
        assert len(eng.trades) == 0
        ses_close = [t for t in eng.closed if t.close_reason == "session_close"]
        assert len(ses_close) >= 1


# ---- plan expiry ----------------------------------------------------

class TestPlanExpiry:
    def test_time_expiry(self):
        cfg = _cfg(entry_mode="Breakout", plan_expire_hours=2.0)
        eng = StrategyEngine(cfg)

        for h in range(20, 24):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(hour=h, minute=m), 100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=0, minute=0), 100, 110, 90, 100))
        for h in range(1, 5):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(day=7, hour=h, minute=m),
                                   100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=5, minute=0), 100, 100, 100, 100))
        assert len(eng.plans) == 2

        # 3 hours later → expired
        events = eng.on_bar(_candle(_ts(day=7, hour=8, minute=0),
                                     100, 100, 100, 100))
        cancel_events = [e for e in events if e["type"] == "CANCEL"]
        assert len(cancel_events) == 2
        assert len(eng.plans) == 0


# ---- state persistence ----------------------------------------------

class TestStatePersistence:
    def test_roundtrip(self):
        cfg = _cfg(entry_mode="Breakout")
        eng = StrategyEngine(cfg)

        for h in range(20, 24):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(hour=h, minute=m), 100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=0, minute=0), 100, 110, 90, 100))
        for h in range(1, 5):
            for m in (0, 30):
                eng.on_bar(_candle(_ts(day=7, hour=h, minute=m),
                                   100, 100, 100, 100))
        eng.on_bar(_candle(_ts(day=7, hour=5, minute=0), 100, 100, 100, 100))

        state = eng.state_dict()
        eng2 = StrategyEngine(cfg)
        eng2.load_state(state)
        assert len(eng2.plans) == len(eng.plans)
