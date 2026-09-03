"""Unit + integration tests for the DowTheoryBreak engine."""

import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import Config
from bot.engine import (
    StrategyEngine, Candle, Plan, OpenTrade, compute_trade_levels, one_r_dist_of,
    ltf_first_hit, ltf_entry_hit,
)
from bot.executor import size_contracts, quantize_str
from bot.indicators import pivot_high, pivot_low, atr_series
from bot.data import bar_to_seconds


# --------------------------------------------------------------------------
# Indicators
# --------------------------------------------------------------------------
def test_pivot_high():
    highs = [1, 2, 5, 2, 1]
    assert pivot_high(highs, 2, 2, 2) == 5
    assert pivot_high(highs, 1, 2, 2) is None  # not enough left bars
    # flat top -> not a strict pivot
    assert pivot_high([1, 5, 5, 5, 1], 2, 2, 2) is None


def test_pivot_low():
    lows = [9, 5, 1, 5, 9]
    assert pivot_low(lows, 2, 2, 2) == 1
    assert pivot_low([9, 1, 1, 1, 9], 2, 2, 2) is None


def test_atr_positive():
    highs = [10, 11, 12, 11, 13, 12, 14]
    lows = [9, 9, 10, 10, 11, 10, 12]
    closes = [9.5, 10.5, 11.5, 10.5, 12.5, 11, 13]
    atr = atr_series(highs, lows, closes, 3)
    assert len(atr) == len(closes)
    assert all(v >= 0 for v in atr)
    assert atr[-1] > 0


# --------------------------------------------------------------------------
# Trade-level math (faithful to Pine)
# --------------------------------------------------------------------------
def _plan(is_buy, top, bot, pb_target, ptype):
    return Plan(id=1, is_buy=is_buy, break_lvl=None, pb_target=pb_target, top=top,
                bot=bot, rng=top - bot, create_bar=0, state=1, any_break=False,
                ptype=ptype, origin_ts=0)


def test_pullback_levels_slpct():
    cfg = Config()  # one_r_basis SL% 25%, rr 1.0
    p = _plan(True, 1100, 1000, 1075, ptype=0)
    ent, sl, tp, one_r, trr = compute_trade_levels(cfg, p, atr_val=0)
    assert ent == 1075
    assert one_r == 25          # rng * 25%
    assert sl == 1050
    assert tp == 1100
    assert math.isclose(trr, 1.0)


def test_pullback_levels_atr():
    cfg = Config()
    cfg.strategy.one_r_basis = "ATR"
    cfg.strategy.one_r_atr_mult = 2.0
    p = _plan(False, 1100, 1000, 1025, ptype=0)   # sell pullback
    ent, sl, tp, one_r, trr = compute_trade_levels(cfg, p, atr_val=7.0)
    assert one_r == 14.0        # atr 7 * mult 2
    assert sl == 1025 + 14
    assert tp == 1025 - 14


def test_mid_levels_rr():
    cfg = Config()               # mid_sl "% of Box" 50, mid_tp "R:R Ratio" 1.0
    p = _plan(True, 1100, 1000, 1075, ptype=1)
    ent, sl, tp, one_r, trr = compute_trade_levels(cfg, p, atr_val=0)
    assert ent == 1075
    assert sl == 1025            # ent - 50% of box
    assert one_r == 50
    assert tp == 1125            # ent + oneR * 1.0
    assert math.isclose(trr, 1.0)


def test_mid_levels_box_edge():
    cfg = Config()
    cfg.strategy.mid_sl_mode = "Box Edge"
    cfg.strategy.mid_tp_mode = "Box Edge"
    p = _plan(False, 1100, 1000, 1025, ptype=1)  # sell mid
    ent, sl, tp, one_r, trr = compute_trade_levels(cfg, p, atr_val=0)
    assert sl == 1100           # opposite (top) edge
    assert tp == 1000           # far (bot) edge


# --------------------------------------------------------------------------
# Sizing
# --------------------------------------------------------------------------
def test_size_contracts_risk_based():
    cfg = Config()
    cfg.sizing.risk_usdt = 50
    cfg.sizing.ct_val = 0.01
    cfg.sizing.lot_size = 1
    cfg.sizing.min_contracts = 1
    # one_r = 25 price units -> 50/25 = 2 BTC -> /0.01 = 200 contracts
    assert size_contracts(cfg, 25) == 200
    assert size_contracts(cfg, 50) == 100


def test_size_contracts_pine():
    cfg = Config()
    cfg.sizing.use_pine_sizing = True
    cfg.sizing.risk_usdt = 500
    cfg.sizing.pip_value_ratio = 100
    cfg.sizing.min_contracts = 0
    cfg.sizing.lot_size = 0
    # 500 / (25 * 100) = 0.2
    assert math.isclose(size_contracts(cfg, 25), 0.2)


# --------------------------------------------------------------------------
# Engine integration
# --------------------------------------------------------------------------
def _zigzag_engine():
    cfg = Config()
    cfg.strategy.dow_swing_len = 2
    for k in cfg.strategy.trade_days:
        cfg.strategy.trade_days[k] = True
    eng = StrategyEngine(cfg, simulate_fills=True)
    amps = [10, 14, 20, 16, 24, 18, 12, 22, 30, 20, 14, 26, 34, 22, 16]
    base = 1000.0
    t = 1_600_000_000_000
    step = 30 * 60 * 1000
    for a in amps:
        for sign in (1, -1):
            for frac in (0.4, 1.0, 0.5):
                px = base + sign * a * frac
                eng.process_candle(Candle(ts=t, open=px, high=px + 2, low=px - 2,
                                          close=px, volume=100))
                t += step
        base += 3
    return eng


def test_engine_detects_patterns_and_trades():
    eng = _zigzag_engine()
    # Patterns should have produced plans and resolved trades.
    assert len(eng.plans) + len(eng.closed_trades) + len(eng.open_trades) > 0
    # Every closed trade has consistent R accounting.
    for t in eng.closed_trades:
        if t.is_win:
            assert t.r > 0
        else:
            assert t.r < 0


def test_win_resolution():
    cfg = Config()
    eng = StrategyEngine(cfg, simulate_fills=True)
    c0 = Candle(ts=1_600_000_000_000, open=1000, high=1002, low=998, close=1000, volume=1)
    eng.process_candle(c0)
    eng.open_trades.append(OpenTrade(
        id=99, is_buy=True, entry=1000, sl=990, tp=1010, bar_idx=0,
        one_r=10, trr=1.0, origin_ts=c0.ts, ptype=0))
    # Next bar reaches TP without touching SL -> win of +trr.
    c1 = Candle(ts=c0.ts + 1, open=1001, high=1010, low=1001, close=1008, volume=1)
    eng.process_candle(c1)
    assert len(eng.closed_trades) == 1
    ct = eng.closed_trades[0]
    assert ct.is_win and math.isclose(ct.r, 1.0)


def test_loss_pessimistic_on_ambiguous_bar():
    cfg = Config()
    eng = StrategyEngine(cfg, simulate_fills=True)
    c0 = Candle(ts=1_600_000_000_000, open=1000, high=1002, low=998, close=1000, volume=1)
    eng.process_candle(c0)
    eng.open_trades.append(OpenTrade(
        id=99, is_buy=True, entry=1000, sl=990, tp=1010, bar_idx=0,
        one_r=10, trr=1.0, origin_ts=c0.ts, ptype=0))
    # Next bar touches BOTH sl and tp -> pessimistic loss.
    c1 = Candle(ts=c0.ts + 1, open=1000, high=1011, low=989, close=1000, volume=1)
    eng.process_candle(c1)
    assert len(eng.closed_trades) == 1
    assert not eng.closed_trades[0].is_win
    assert eng.closed_trades[0].r < 0


def test_trade_day_filter_blocks_plan():
    cfg = Config()
    cfg.strategy.use_mid_level = False
    cfg.strategy.trade_days["sun"] = False
    eng = StrategyEngine(cfg, simulate_fills=True)
    # 2021-01-03 is a Sunday (UTC).
    sun = int(datetime(2021, 1, 3, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
    eng.times = [sun]
    eng.closes = [1050]
    eng.bar_index = 0
    events = []
    eng._create_plans(True, 1100, 1000, 0, events)
    assert len(eng.plans) == 0                 # blocked
    assert any(e.get("note") == "no-trade-day" for e in events)


# --------------------------------------------------------------------------
# Intrabar (lower-TF) disambiguation — Pine's f_ltfFirstHit / f_ltfEntryHit
# --------------------------------------------------------------------------
def test_bar_to_seconds():
    assert bar_to_seconds("30m") == 1800
    assert bar_to_seconds("1H") == 3600
    assert bar_to_seconds("1m") == 60
    assert bar_to_seconds("1D") == 86400


def test_ltf_first_hit_sl_before_tp():
    # Buy: sub-bars ascending in time; SL touched in the 2nd sub-bar, TP later.
    subbars = [(1005, 995), (1000, 989), (1015, 1005)]  # (high, low)
    assert ltf_first_hit(subbars, True, sl=990, tp=1012) == 1


def test_ltf_first_hit_tp_before_sl():
    subbars = [(1012, 1000), (1015, 1001), (1002, 989)]
    assert ltf_first_hit(subbars, True, sl=990, tp=1012) == 2


def test_ltf_first_hit_same_subbar_is_pessimistic():
    # Both SL and TP touched within the very same sub-bar -> SL wins (Pine order).
    subbars = [(1020, 985)]
    assert ltf_first_hit(subbars, True, sl=990, tp=1012) == 1


def test_ltf_first_hit_neither():
    subbars = [(1005, 998), (1006, 999)]
    assert ltf_first_hit(subbars, True, sl=990, tp=1012) == 0


def test_ltf_entry_hit_sl_proven_after_fill():
    # Buy limit at 1000: fills in sub-bar 2, SL(990) touched in sub-bar 4.
    subbars = [
        (1010, 1005),   # before fill
        (1010, 998),    # fills here (low <= 1000)
        (1005, 999),
        (1004, 985),    # SL touched, proven post-fill
    ]
    assert ltf_entry_hit(subbars, True, ent=1000, sl=990, tp=1020) == 1


def test_ltf_entry_hit_tp_on_fill_subbar_ignored():
    # TP touched in the SAME sub-bar as the fill -> ignored (ambiguous order).
    subbars = [(1025, 998)]  # low<=1000 fills; high>=1020 also true, but ignored
    assert ltf_entry_hit(subbars, True, ent=1000, sl=990, tp=1020) == 0


def test_ltf_entry_hit_tp_after_fill():
    subbars = [
        (1010, 998),    # fills
        (1025, 1010),   # TP proven post-fill
    ]
    assert ltf_entry_hit(subbars, True, ent=1000, sl=990, tp=1020) == 2


def test_engine_uses_ltf_provider_to_flip_ambiguous_loss_to_win():
    cfg = Config()
    provider_calls = []

    def provider(ts):
        provider_calls.append(ts)
        # TP touched before SL within the ambiguous bar -> should resolve WIN.
        return [(1012, 1002), (1002, 989)]

    eng = StrategyEngine(cfg, simulate_fills=True, ltf_provider=provider)
    c0 = Candle(ts=1_600_000_000_000, open=1000, high=1002, low=998, close=1000, volume=1)
    eng.process_candle(c0)
    eng.open_trades.append(OpenTrade(
        id=1, is_buy=True, entry=1000, sl=990, tp=1010, bar_idx=0,
        one_r=10, trr=1.0, origin_ts=c0.ts, ptype=0))
    # Ambiguous: both SL(990) and TP(1010) touched on this bar.
    c1 = Candle(ts=c0.ts + 1, open=1000, high=1011, low=989, close=1000, volume=1)
    eng.process_candle(c1)
    assert len(eng.closed_trades) == 1
    assert eng.closed_trades[0].is_win  # flipped from the pessimistic default
    assert provider_calls == [c1.ts]


def test_size_contracts_floors_to_lot():
    cfg = Config()
    cfg.sizing.risk_usdt = 50
    cfg.sizing.ct_val = 0.01
    cfg.sizing.lot_size = 1
    cfg.sizing.min_contracts = 1
    # 50/26 = 1.923 BTC -> 192.3 contracts -> floors to 192 (never risk more)
    assert size_contracts(cfg, 26) == 192


def test_quantize_str_tick_size():
    assert quantize_str(65123.44, 0.1) == "65123.4"
    assert quantize_str(65123.45678, 0.1) == "65123.5"
    assert quantize_str(65000.0, 0.1) == "65000"
    assert quantize_str(0.2, 0) == "0.2"          # step 0 -> passthrough, no sci notation


def test_cancel_event_carries_signature():
    cfg = Config()
    eng = StrategyEngine(cfg, simulate_fills=False)
    c0 = Candle(ts=1_600_000_000_000, open=1000, high=1002, low=998, close=1000, volume=1)
    eng.process_candle(c0)
    p = Plan(id=5, is_buy=True, break_lvl=1100, pb_target=1075, top=1100, bot=1000,
             rng=100, create_bar=-200, state=1, any_break=False, ptype=0,
             origin_ts=123456, armed=True)
    eng.plans.append(p)
    c1 = Candle(ts=c0.ts + 1, open=1000, high=1002, low=998, close=1000, volume=1)
    events = eng.process_candle(c1)
    cancels = [e for e in events if e["type"] == "CANCEL"]
    assert len(cancels) == 1
    ev = cancels[0]
    assert ev["origin_ts"] == 123456 and ev["ptype"] == 0 and ev["is_buy"] is True


def test_mid_plan_arms_at_creation_in_live_mode():
    cfg = Config()
    eng = StrategyEngine(cfg, simulate_fills=False)
    # 2021-01-05 is a Tuesday (allowed trade day by default).
    tue = int(datetime(2021, 1, 5, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
    eng.times = [tue]
    eng.closes = [1090]   # close > mid entry (1075) -> mid plan is created
    eng.bar_index = 0
    events = []
    eng._create_plans(True, 1100, 1000, 0, events)
    mid_arms = [e for e in events if e["type"] == "ARM" and e["ptype"] == 1]
    assert len(mid_arms) == 1
    assert math.isclose(mid_arms[0]["entry"], 1075)


def test_dow_name():
    cfg = Config()
    eng = StrategyEngine(cfg)
    sun = int(datetime(2021, 1, 3, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    mon = int(datetime(2021, 1, 4, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    sat = int(datetime(2021, 1, 2, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert eng._dow_name(sun) == "sun"
    assert eng._dow_name(mon) == "mon"
    assert eng._dow_name(sat) == "sat"
