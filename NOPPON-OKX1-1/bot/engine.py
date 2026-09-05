"""Session Breakout strategy engine — faithful port of NOPPON-GOLD1-1 Pine.

State machine:
  1. Track session windows (Sydney/Tokyo/London/NY) per bar.
  2. On session end → create OCO plan pair (Buy Stop + Sell Stop).
  3. Plans go through entry modes (Breakout / Pullback / PB+Re-break).
  4. Triggered plan → open trade, cancel OCO partner.
  5. Open trades check TP/SL, trailing SL, 2nd-order rescue, 50% add-on.
  6. Close-on-new-session closes open main orders when a new session starts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

from .config import Config, SessionDef, StrategyConfig
from .indicators import atr_series


@dataclass
class Candle:
    ts: int       # bar open timestamp (ms, UTC)
    o: float
    h: float
    l: float
    c: float
    vol: float = 0.0


@dataclass
class Plan:
    oco_id: int
    session_name: str
    is_buy: bool
    entry: float        # session edge (hi for buy, lo for sell)
    sl: float
    tp: float
    lot: float
    trade_rr: float
    ses_range: float
    state: int = 0      # 0=waiting breakout, 1=waiting pullback, 2=waiting re-break
    create_ts: int = 0
    plan_id: int = 0    # unique auto-increment


@dataclass
class OpenTrade:
    is_buy: bool
    entry: float
    sl: float
    tp: float
    bar_idx: int
    pips_dist: float    # 1R distance
    trade_rr: float
    is_2nd: bool = False
    is_addon: bool = False
    trailed: bool = False
    sl_r: float = -1.0
    ses_range: float = 0.0
    ses_name: str = ""
    origin_ts: int = 0
    orig_entry: float = 0.0
    addon_tpd: bool = False
    trade_id: int = 0


@dataclass
class SecondPending:
    is_buy: bool
    entry: float
    ses_range: float
    ses_name: str
    origin_ts: int
    orig_entry: float


@dataclass
class AddonPending:
    is_buy: bool
    level: float       # 50% trigger price
    tp: float          # main entry
    sl: float          # main SL
    ses_range: float
    ses_name: str
    origin_ts: int     # main's bar timestamp (link key)


@dataclass
class ClosedTrade:
    is_buy: bool
    entry: float
    sl: float
    tp: float
    is_win: bool
    r: float
    close_pts: float
    is_2nd: bool
    is_addon: bool
    origin_ts: int
    close_ts: int
    close_reason: str = "tp_sl"  # "tp_sl" | "session_close"


@dataclass
class SessionRuntime:
    name: str
    active: bool = False
    hi: float = float("nan")
    lo: float = float("nan")
    start_bar_idx: int = -1


DOW_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


def _parse_ses_time(s: str) -> Tuple[int, int]:
    """Parse 'HHMM-HHMM' → (start_minutes, end_minutes) from midnight UTC."""
    h1, m1 = int(s[0:2]), int(s[2:4])
    h2, m2 = int(s[5:7]), int(s[7:9])
    return h1 * 60 + m1, h2 * 60 + m2


def _bar_in_session(bar_ts_ms: int, bar_len_min: int,
                    ses_start: int, ses_end: int,
                    tz_offset_hours: int = 0) -> bool:
    """Check if bar overlaps with session window (mirrors Pine inSessionOverlap)."""
    dt = datetime.fromtimestamp(bar_ts_ms / 1000, tz=timezone.utc)
    dt_local = dt + timedelta(hours=tz_offset_hours)
    bar_min = dt_local.hour * 60 + dt_local.minute
    bar_end = bar_min + max(1, bar_len_min)

    if ses_start < ses_end:
        return bar_min < ses_end and bar_end > ses_start
    elif ses_start > ses_end:
        return (bar_min >= ses_start or bar_min < ses_end or
                bar_end > ses_start or
                (bar_end > 1440 and (bar_end - 1440) > 0))
    return False


def _is_dst(ts_ms: int, tz_offset: int = 0) -> bool:
    """Apr-Sep → DST (same simplified rule as Pine)."""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    dt_local = dt + timedelta(hours=tz_offset)
    return 4 <= dt_local.month <= 9


def _day_of_week(ts_ms: int, tz_offset: int = 0) -> int:
    """Return 0=Mon..6=Sun (Python convention). We map to our DOW_NAMES."""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    dt_local = dt + timedelta(hours=tz_offset)
    return dt_local.weekday()


def one_r_dist_of(cfg: StrategyConfig, ses_range: float,
                  atr_val: float = 0.0) -> float:
    if cfg.one_r_basis == "Distance":
        return cfg.one_r_dist_fix
    elif cfg.one_r_basis == "ATR":
        return atr_val * cfg.one_r_atr_mult
    else:
        return ses_range * (cfg.one_r_pct_val / 100.0)


class StrategyEngine:
    def __init__(self, cfg: Config, live: bool = False):
        self.cfg = cfg
        self.s = cfg.strategy
        self.live = live

        self.sessions_rt: List[SessionRuntime] = []
        for sd in self.s.sessions:
            if sd.enabled:
                self.sessions_rt.append(SessionRuntime(name=sd.name))

        self.plans: List[Plan] = []
        self.trades: List[OpenTrade] = []
        self.second_pending: List[SecondPending] = []
        self.addon_pending: List[AddonPending] = []
        self.closed: List[ClosedTrade] = []

        self._oco_counter = 0
        self._plan_counter = 0
        self._trade_counter = 0
        self._bar_idx = -1

        self._highs: List[float] = []
        self._lows: List[float] = []
        self._closes: List[float] = []

        self._use_pullback = self.s.entry_mode in ("Pullback", "PBRebreak")
        self._use_pb_rebreak = self.s.entry_mode == "PBRebreak"

    # ------------------------------------------------------------------
    @property
    def _bar_len_min(self) -> int:
        bar = self.cfg.exchange.bar
        if bar.endswith("m"):
            return int(bar[:-1])
        if bar.endswith("H"):
            return int(bar[:-1]) * 60
        if bar.endswith("D") or bar.endswith("d"):
            return 1440
        return 30

    def _get_atr(self) -> float:
        if len(self._closes) < self.s.one_r_atr_period:
            return 0.0
        vals = atr_series(self._highs, self._lows, self._closes,
                          self.s.one_r_atr_period)
        v = vals[-1]
        return v if not math.isnan(v) else 0.0

    def _next_plan_id(self) -> int:
        self._plan_counter += 1
        return self._plan_counter

    def _next_trade_id(self) -> int:
        self._trade_counter += 1
        return self._trade_counter

    def _session_def(self, name: str) -> Optional[SessionDef]:
        for sd in self.s.sessions:
            if sd.name == name:
                return sd
        return None

    # ------------------------------------------------------------------
    def on_bar(self, candle: Candle) -> List[Dict]:
        """Process one closed bar, return events for executor."""
        self._bar_idx += 1
        self._highs.append(candle.h)
        self._lows.append(candle.l)
        self._closes.append(candle.c)

        events: List[Dict] = []

        atr_val = self._get_atr() if self.s.one_r_basis == "ATR" else 0.0
        tz_off = self.s.tz_offset_hours
        bar_len = self._bar_len_min

        # --- 1. Session tracking ---
        for srt in self.sessions_rt:
            sd = self._session_def(srt.name)
            if sd is None:
                continue
            dst = _is_dst(candle.ts, tz_off)
            ses_str = sd.dst_time_str if dst else sd.time_str
            ses_start, ses_end = _parse_ses_time(ses_str)
            is_ses = _bar_in_session(candle.ts, bar_len, ses_start, ses_end, tz_off)

            ses_start_ev = is_ses and not srt.active
            ses_end_ev = not is_ses and srt.active
            srt.active = is_ses

            if ses_start_ev:
                events.extend(self._on_session_start(srt, candle))
                srt.start_bar_idx = self._bar_idx
                srt.hi = candle.h
                srt.lo = candle.l

            if is_ses and not ses_start_ev:
                srt.hi = max(srt.hi, candle.h) if not math.isnan(srt.hi) else candle.h
                srt.lo = min(srt.lo, candle.l) if not math.isnan(srt.lo) else candle.l

            if ses_end_ev and not math.isnan(srt.hi) and not math.isnan(srt.lo):
                ses_range = srt.hi - srt.lo
                if ses_range > 0:
                    events.extend(self._on_session_end(
                        srt, candle, ses_range, atr_val))

        # --- 2. Plan expiry ---
        if self.s.plan_expire_hours > 0:
            events.extend(self._check_plan_expiry(candle))

        # --- 3. Plan trigger check ---
        events.extend(self._check_plans(candle, atr_val))

        # --- 4. 2nd order re-break check ---
        events.extend(self._check_2nd_pending(candle, atr_val))

        # --- 5. 50% Add-on check ---
        events.extend(self._check_addon_pending(candle, atr_val))

        # --- 6. Trade TP/SL + trailing ---
        events.extend(self._check_trades(candle))

        return events

    # ------------------------------------------------------------------
    def _on_session_start(self, srt: SessionRuntime, candle: Candle) -> List[Dict]:
        events: List[Dict] = []
        name = srt.name

        # Cancel pending plans for this session (when expire=0 → cancel at new session)
        if self.s.plan_expire_hours == 0:
            i = len(self.plans) - 1
            while i >= 0:
                if self.plans[i].session_name == name:
                    p = self.plans.pop(i)
                    events.append({"type": "CANCEL", "plan_id": p.plan_id,
                                   "session_name": name, "is_buy": p.is_buy,
                                   "oco_id": p.oco_id, "entry": p.entry})
                i -= 1

        # Cancel 2nd order pending
        if self.s.use_2nd_order:
            self.second_pending = [
                sp for sp in self.second_pending if sp.ses_name != name]

        # Cancel add-on pending
        if self.s.use_addon_50:
            self.addon_pending = [
                ap for ap in self.addon_pending if ap.ses_name != name]

        # Close main orders on new session
        if self.s.close_main_on_new_ses:
            i = len(self.trades) - 1
            while i >= 0:
                t = self.trades[i]
                keep_addon = self.s.addon_keep_open and t.is_addon
                if not keep_addon:
                    pnl_dist = (candle.c - t.entry) if t.is_buy else (t.entry - candle.c)
                    actual_r = pnl_dist / t.pips_dist if t.pips_dist > 0 else 0.0
                    ct = ClosedTrade(
                        is_buy=t.is_buy, entry=t.entry, sl=t.sl, tp=t.tp,
                        is_win=actual_r > 0, r=actual_r,
                        close_pts=abs(pnl_dist), is_2nd=t.is_2nd,
                        is_addon=t.is_addon, origin_ts=t.origin_ts,
                        close_ts=candle.ts, close_reason="session_close")
                    self.closed.append(ct)
                    events.append({"type": "CLOSE_SESSION",
                                   "trade_id": t.trade_id, "is_buy": t.is_buy,
                                   "entry": t.entry, "close_px": candle.c,
                                   "r": actual_r})
                    self.trades.pop(i)
                i -= 1

        return events

    # ------------------------------------------------------------------
    def _on_session_end(self, srt: SessionRuntime, candle: Candle,
                        ses_range: float, atr_val: float) -> List[Dict]:
        events: List[Dict] = []

        # Trade day filter
        py_dow = _day_of_week(candle.ts, self.s.tz_offset_hours)
        dow_name = DOW_NAMES[py_dow]
        if not self.s.trade_days.get(dow_name, True):
            return events

        self._oco_counter += 1
        oco_id = self._oco_counter

        one_r = one_r_dist_of(self.s, ses_range, atr_val)

        # --- BUY PLAN ---
        b_entry = srt.hi
        b_ent_adj = b_entry + self.s.spread_pts
        b_sl = srt.lo if self.s.sl_edge_mode else b_ent_adj - one_r
        b_risk = abs(b_ent_adj - b_sl)
        b_reward_base = b_risk if self.s.rr_base_mode == "SLDistance" else one_r
        b_tp = b_ent_adj + b_reward_base * self.s.rr_ratio
        b_lot = self.s.risk_amount / (one_r * self.s.pip_value_ratio) if one_r > 0 else 0.0
        b_trr = abs(b_tp - b_ent_adj) / one_r if one_r > 0 else 0.0

        b_plan = Plan(
            oco_id=oco_id, session_name=srt.name, is_buy=True,
            entry=b_entry, sl=b_sl, tp=b_tp, lot=b_lot,
            trade_rr=b_trr, ses_range=ses_range,
            state=0, create_ts=candle.ts, plan_id=self._next_plan_id())
        self.plans.append(b_plan)

        # --- SELL PLAN ---
        s_entry = srt.lo
        s_ent_adj = s_entry - self.s.spread_pts
        s_sl = srt.hi if self.s.sl_edge_mode else s_ent_adj + one_r
        s_risk = abs(s_sl - s_ent_adj)
        s_reward_base = s_risk if self.s.rr_base_mode == "SLDistance" else one_r
        s_tp = s_ent_adj - s_reward_base * self.s.rr_ratio
        s_lot = self.s.risk_amount / (one_r * self.s.pip_value_ratio) if one_r > 0 else 0.0
        s_trr = abs(s_ent_adj - s_tp) / one_r if one_r > 0 else 0.0

        s_plan = Plan(
            oco_id=oco_id, session_name=srt.name, is_buy=False,
            entry=s_entry, sl=s_sl, tp=s_tp, lot=s_lot,
            trade_rr=s_trr, ses_range=ses_range,
            state=0, create_ts=candle.ts, plan_id=self._next_plan_id())
        self.plans.append(s_plan)

        events.append({"type": "PLAN_CREATED", "oco_id": oco_id,
                        "session": srt.name, "hi": srt.hi, "lo": srt.lo,
                        "range": ses_range})

        return events

    # ------------------------------------------------------------------
    def _check_plan_expiry(self, candle: Candle) -> List[Dict]:
        events: List[Dict] = []
        exp_ms = int(self.s.plan_expire_hours * 3600 * 1000)
        i = len(self.plans) - 1
        while i >= 0:
            p = self.plans[i]
            if (candle.ts - p.create_ts) > exp_ms:
                oco = p.oco_id
                self.plans.pop(i)
                events.append({"type": "CANCEL", "plan_id": p.plan_id,
                               "session_name": p.session_name,
                               "is_buy": p.is_buy, "oco_id": oco,
                               "entry": p.entry, "reason": "expired"})
                # Cancel OCO partner
                j = len(self.plans) - 1
                while j >= 0:
                    if self.plans[j].oco_id == oco:
                        pp = self.plans.pop(j)
                        events.append({"type": "CANCEL", "plan_id": pp.plan_id,
                                       "session_name": pp.session_name,
                                       "is_buy": pp.is_buy, "oco_id": oco,
                                       "entry": pp.entry, "reason": "oco_expired"})
                        if j < i:
                            i -= 1
                        break
                    j -= 1
            i -= 1
        return events

    # ------------------------------------------------------------------
    def _check_plans(self, candle: Candle, atr_val: float) -> List[Dict]:
        events: List[Dict] = []
        pb_pct = self.s.pullback_range_pct / 100.0

        i = len(self.plans) - 1
        while i >= 0:
            if i >= len(self.plans):
                i -= 1
                continue
            p = self.plans[i]
            ent = p.entry
            is_b = p.is_buy
            state = p.state
            ses_range = p.ses_range
            pb_dist = ses_range * pb_pct
            pb_price = (ent - pb_dist) if is_b else (ent + pb_dist)

            triggered = False

            if self._use_pullback:
                if state == 0:
                    if (is_b and candle.h > ent) or (not is_b and candle.l < ent):
                        p.state = 1
                elif state == 1:
                    if (is_b and candle.l <= pb_price) or (not is_b and candle.h >= pb_price):
                        if self._use_pb_rebreak:
                            p.state = 2
                        else:
                            triggered = True
                            ent = pb_price
                elif state == 2:
                    if (is_b and candle.h > ent) or (not is_b and candle.l < ent):
                        triggered = True
            else:
                if (is_b and candle.h > ent) or (not is_b and candle.l < ent):
                    triggered = True

            if triggered:
                events.extend(self._trigger_plan(i, ent, candle, atr_val))
            else:
                i -= 1

        return events

    def _trigger_plan(self, idx: int, ent: float, candle: Candle,
                      atr_val: float) -> List[Dict]:
        events: List[Dict] = []
        p = self.plans[idx]
        is_b = p.is_buy
        oco_id = p.oco_id
        ses_range = p.ses_range
        orig_entry = p.entry

        ent += self.s.spread_pts if is_b else -self.s.spread_pts

        one_r = one_r_dist_of(self.s, ses_range, atr_val)

        if self.s.sl_edge_mode:
            sl = (orig_entry - ses_range) if is_b else (orig_entry + ses_range)
        else:
            sl = (ent - one_r) if is_b else (ent + one_r)

        tp = p.tp
        lot = p.lot
        trade_rr = p.trade_rr
        r_dist = one_r
        dist = abs(ent - sl)

        if self._use_pullback:
            reward_base = dist if self.s.rr_base_mode == "SLDistance" else r_dist
            tp = (ent + reward_base * self.s.rr_ratio) if is_b else (ent - reward_base * self.s.rr_ratio)
            lot = self.s.risk_amount / (r_dist * self.s.pip_value_ratio) if r_dist > 0 else 0.0
            trade_rr = abs(ent - tp) / r_dist if r_dist > 0 else 0.0

        trade = OpenTrade(
            is_buy=is_b, entry=ent, sl=sl, tp=tp,
            bar_idx=self._bar_idx, pips_dist=r_dist, trade_rr=trade_rr,
            is_2nd=False, is_addon=False,
            ses_range=ses_range, ses_name=p.session_name,
            origin_ts=candle.ts, orig_entry=orig_entry,
            trade_id=self._next_trade_id())
        self.trades.append(trade)

        events.append({"type": "FILL", "trade_id": trade.trade_id,
                       "is_buy": is_b, "entry": ent, "sl": sl, "tp": tp,
                       "one_r": r_dist, "lot": lot, "trr": trade_rr,
                       "session": p.session_name})

        # Arm 50% add-on
        if self.s.use_addon_50:
            ao_mid = (orig_entry - ses_range / 2) if is_b else (orig_entry + ses_range / 2)
            ao_valid = (ent > ao_mid and sl <= ao_mid) if is_b else (ent < ao_mid and sl >= ao_mid)
            if ao_valid:
                self.addon_pending.append(AddonPending(
                    is_buy=is_b, level=ao_mid, tp=ent, sl=sl,
                    ses_range=ses_range, ses_name=p.session_name,
                    origin_ts=candle.ts))

        # Remove triggered plan
        self.plans.pop(idx)

        # Cancel OCO partner
        j = len(self.plans) - 1
        while j >= 0:
            if self.plans[j].oco_id == oco_id:
                pp = self.plans.pop(j)
                events.append({"type": "CANCEL", "plan_id": pp.plan_id,
                               "session_name": pp.session_name,
                               "is_buy": pp.is_buy, "oco_id": oco_id,
                               "entry": pp.entry, "reason": "oco_fill"})
                break
            j -= 1

        return events

    # ------------------------------------------------------------------
    def _check_2nd_pending(self, candle: Candle, atr_val: float) -> List[Dict]:
        if not self.s.use_2nd_order:
            return []
        events: List[Dict] = []
        i = len(self.second_pending) - 1
        while i >= 0:
            sp = self.second_pending[i]
            triggered = (candle.h >= sp.entry) if sp.is_buy else (candle.l <= sp.entry)
            if triggered:
                ent = sp.entry + (self.s.spread_pts if sp.is_buy else -self.s.spread_pts)
                one_r = one_r_dist_of(self.s, sp.ses_range, atr_val)
                if self.s.sl_edge_mode:
                    sl = (sp.orig_entry - sp.ses_range) if sp.is_buy else (sp.orig_entry + sp.ses_range)
                else:
                    sl = (ent - one_r) if sp.is_buy else (ent + one_r)
                risk_d = abs(ent - sl)
                rr = self.s.second_rr if self.s.use_2nd_custom_rr else self.s.rr_ratio
                reward_base = risk_d if self.s.rr_base_mode == "SLDistance" else one_r
                tp = (ent + reward_base * rr) if sp.is_buy else (ent - reward_base * rr)
                lot = self.s.risk_amount / (one_r * self.s.pip_value_ratio) if one_r > 0 else 0.0
                trd_rr = abs(tp - ent) / one_r if one_r > 0 else 0.0

                trade = OpenTrade(
                    is_buy=sp.is_buy, entry=ent, sl=sl, tp=tp,
                    bar_idx=self._bar_idx, pips_dist=one_r, trade_rr=trd_rr,
                    is_2nd=True, is_addon=False,
                    ses_range=sp.ses_range, ses_name=sp.ses_name,
                    origin_ts=candle.ts, orig_entry=sp.orig_entry,
                    trade_id=self._next_trade_id())
                self.trades.append(trade)
                events.append({"type": "FILL_2ND", "trade_id": trade.trade_id,
                               "is_buy": sp.is_buy, "entry": ent, "sl": sl,
                               "tp": tp, "one_r": one_r, "lot": lot,
                               "trr": trd_rr})
                self.second_pending.pop(i)
            i -= 1
        return events

    # ------------------------------------------------------------------
    def _check_addon_pending(self, candle: Candle, atr_val: float) -> List[Dict]:
        if not self.s.use_addon_50:
            return []
        events: List[Dict] = []
        i = len(self.addon_pending) - 1
        while i >= 0:
            ap = self.addon_pending[i]
            hit = (candle.ts > ap.origin_ts and
                   ((ap.is_buy and candle.l <= ap.level) or
                    (not ap.is_buy and candle.h >= ap.level)))
            if hit:
                main_alive = False
                for t in self.trades:
                    if (not t.is_2nd and not t.is_addon and
                            t.is_buy == ap.is_buy and
                            t.origin_ts == ap.origin_ts and
                            t.ses_name == ap.ses_name):
                        main_alive = True
                        break
                if main_alive:
                    a_entry = ap.level + (self.s.spread_pts if ap.is_buy else -self.s.spread_pts)
                    a_sl = ap.sl
                    a_risk_d = abs(a_entry - a_sl)
                    if self.s.addon_tp_mode == "RR":
                        a_tp = (a_entry + a_risk_d * self.s.addon_rr) if ap.is_buy else (a_entry - a_risk_d * self.s.addon_rr)
                    else:
                        a_tp = ap.tp
                    a_lot = self.s.risk_amount / (a_risk_d * self.s.pip_value_ratio) if a_risk_d > 0 else 0.0
                    a_rr = abs(a_tp - a_entry) / a_risk_d if a_risk_d > 0 else 0.0

                    trade = OpenTrade(
                        is_buy=ap.is_buy, entry=a_entry, sl=a_sl, tp=a_tp,
                        bar_idx=self._bar_idx, pips_dist=a_risk_d,
                        trade_rr=a_rr, is_2nd=True, is_addon=True,
                        ses_range=ap.ses_range, ses_name=ap.ses_name,
                        origin_ts=candle.ts, orig_entry=ap.tp,
                        trade_id=self._next_trade_id())
                    self.trades.append(trade)
                    events.append({"type": "FILL_ADDON", "trade_id": trade.trade_id,
                                   "is_buy": ap.is_buy, "entry": a_entry,
                                   "sl": a_sl, "tp": a_tp, "lot": a_lot,
                                   "trr": a_rr})

                    # Move main TP to break-even if enabled
                    if self.s.addon_main_be:
                        for t in self.trades:
                            if (not t.is_2nd and not t.is_addon and
                                    t.is_buy == ap.is_buy and
                                    t.origin_ts == ap.origin_ts and
                                    t.ses_name == ap.ses_name):
                                t.tp = t.entry
                                t.trade_rr = 0.0
                                break

                self.addon_pending.pop(i)
            i -= 1
        return events

    # ------------------------------------------------------------------
    def _check_trades(self, candle: Candle) -> List[Dict]:
        events: List[Dict] = []
        i = len(self.trades) - 1
        while i >= 0:
            t = self.trades[i]
            if self._bar_idx <= t.bar_idx:
                i -= 1
                continue

            # --- Trailing SL ---
            if self.s.use_trail and not t.trailed and t.pips_dist > 0:
                trig_px = (t.entry + t.pips_dist * self.s.trail_trigger_r) if t.is_buy else \
                          (t.entry - t.pips_dist * self.s.trail_trigger_r)
                new_sl = (t.entry + t.pips_dist * self.s.trail_lock_r) if t.is_buy else \
                         (t.entry - t.pips_dist * self.s.trail_lock_r)
                trail_hit = (candle.h >= trig_px) if t.is_buy else (candle.l <= trig_px)
                if trail_hit:
                    t.sl = new_sl
                    t.trailed = True
                    t.sl_r = self.s.trail_lock_r

            # --- TP/SL check ---
            closed_win = False
            closed_loss = False
            if t.is_buy:
                if candle.l <= t.sl:
                    closed_loss = True
                elif candle.h >= t.tp:
                    closed_win = True
            else:
                if candle.h >= t.sl:
                    closed_loss = True
                elif candle.l <= t.tp:
                    closed_win = True

            if closed_win or closed_loss:
                is_trail_stop = closed_loss and t.trailed
                dist = t.pips_dist
                loss_r = -(abs(t.entry - t.sl) / dist) if dist > 0 else -1.0
                actual_r = t.trade_rr if closed_win else (t.sl_r if is_trail_stop else loss_r)
                close_pts = abs(t.tp - t.entry) if closed_win else abs(t.sl - t.entry)

                ct = ClosedTrade(
                    is_buy=t.is_buy, entry=t.entry, sl=t.sl, tp=t.tp,
                    is_win=actual_r > 0, r=actual_r, close_pts=close_pts,
                    is_2nd=t.is_2nd, is_addon=t.is_addon,
                    origin_ts=t.origin_ts, close_ts=candle.ts)
                self.closed.append(ct)

                events.append({"type": "TRADE_CLOSED", "trade_id": t.trade_id,
                               "is_buy": t.is_buy, "is_win": actual_r > 0,
                               "r": actual_r, "entry": t.entry,
                               "close_px": t.tp if closed_win else t.sl})

                # Add-on TP flag: mark parent main
                if t.is_addon and closed_win:
                    for mt in self.trades:
                        if (not mt.is_2nd and not mt.is_addon and
                                mt.ses_name == t.ses_name and
                                mt.is_buy == t.is_buy and
                                mt.orig_entry == t.orig_entry):
                            mt.addon_tpd = True
                            break

                # 2nd order pending on main SL
                if (self.s.use_2nd_order and not t.is_2nd and not t.is_addon and
                        closed_loss and not is_trail_stop and not t.addon_tpd):
                    self.second_pending.append(SecondPending(
                        is_buy=t.is_buy, entry=t.entry, ses_range=t.ses_range,
                        ses_name=t.ses_name, origin_ts=candle.ts,
                        orig_entry=t.orig_entry))

                # Cancel linked add-on pending if main closed
                if not t.is_2nd and not t.is_addon:
                    self.addon_pending = [
                        ap for ap in self.addon_pending
                        if not (ap.origin_ts == t.origin_ts and
                                ap.ses_name == t.ses_name and
                                ap.is_buy == t.is_buy)]

                self.trades.pop(i)

            i -= 1

        return events

    # ------------------------------------------------------------------
    def state_dict(self) -> dict:
        return {
            "plans": [asdict(p) for p in self.plans],
            "trades": [asdict(t) for t in self.trades],
            "second_pending": [asdict(s) for s in self.second_pending],
            "addon_pending": [asdict(a) for a in self.addon_pending],
            "sessions_rt": [asdict(s) for s in self.sessions_rt],
            "oco_counter": self._oco_counter,
            "plan_counter": self._plan_counter,
            "trade_counter": self._trade_counter,
            "bar_idx": self._bar_idx,
        }

    def load_state(self, data: dict):
        self.plans = [Plan(**p) for p in data.get("plans", [])]
        self.trades = [OpenTrade(**t) for t in data.get("trades", [])]
        self.second_pending = [SecondPending(**s) for s in data.get("second_pending", [])]
        self.addon_pending = [AddonPending(**a) for a in data.get("addon_pending", [])]
        for sd in data.get("sessions_rt", []):
            for srt in self.sessions_rt:
                if srt.name == sd["name"]:
                    srt.active = sd["active"]
                    srt.hi = sd["hi"]
                    srt.lo = sd["lo"]
                    srt.start_bar_idx = sd["start_bar_idx"]
        self._oco_counter = data.get("oco_counter", 0)
        self._plan_counter = data.get("plan_counter", 0)
        self._trade_counter = data.get("trade_counter", 0)
        self._bar_idx = data.get("bar_idx", -1)
