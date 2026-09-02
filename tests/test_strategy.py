"""Unit + integration tests for the DowTheoryBreak engine."""

import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import Config
from bot.engine import (
    StrategyEngine, Candle, Plan, OpenTrade, compute_trade_levels, one_r_dist_of,
)
from bot.executor import size_contracts
from bot.indicators import pivot_high, pivot_low, atr_series


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


def test_dow_name():
    cfg = Config()
    eng = StrategyEngine(cfg)
    sun = int(datetime(2021, 1, 3, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    mon = int(datetime(2021, 1, 4, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    sat = int(datetime(2021, 1, 2, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert eng._dow_name(sun) == "sun"
    assert eng._dow_name(mon) == "mon"
    assert eng._dow_name(sat) == "sat"
