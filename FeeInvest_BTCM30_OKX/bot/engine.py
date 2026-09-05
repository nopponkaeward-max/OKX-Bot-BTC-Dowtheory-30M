"""Pure strategy engine — a bar-for-bar port of DowTheoryBreak_V1.0.

The engine consumes *confirmed* candles one at a time (oldest first) and
reproduces the Pine logic in the same intra-bar order:

    1. swing / pattern detection (pivots)
    2. pattern box + plan creation (pullback + mid-level)
    3. plan state machine (break -> pullback -> fill)
    4. trade result resolution           (backtest only)

Two operating modes share this code:

* ``simulate_fills=True``  (backtest) — the engine simulates limit fills and
  resolves win/loss exactly like the indicator, appending to ``closed_trades``.
* ``simulate_fills=False`` (live)     — the engine stops at the moment an order
  should rest on the exchange and emits an ``ARM`` event; ``CANCEL`` events are
  emitted on expiry / mid-cancel.  Real fills are owned by the executor.

Nothing here talks to a network, so it is fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import Config
from .indicators import pivot_high, pivot_low, atr_series


DAY_NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]

# A lower-timeframe provider returns ascending (high, low) sub-bar tuples for
# the *current* parent bar's timestamp, or None if no intrabar data exists
# (mirrors Pine's ``array.size(ltfL) > 0`` guard -> pessimistic fallback).
LtfProviderT = Callable[[int], Optional[List[Tuple[float, float]]]]


def ltf_first_hit(subbars: List[Tuple[float, float]], is_buy: bool,
                  sl: float, tp: float) -> int:
    """Port of Pine's ``f_ltfFirstHit`` — which of SL/TP is touched first.

    Returns 0 (neither), 1 (SL first) or 2 (TP first). SL wins when both are
    touched within the same sub-bar (pessimistic ambiguity, same as Pine).
    """
    for h, l in subbars:
        hit_sl = (l <= sl) if is_buy else (h >= sl)
        hit_tp = (h >= tp) if is_buy else (l <= tp)
        if hit_sl:
            return 1
        if hit_tp:
            return 2
    return 0


def ltf_entry_hit(subbars: List[Tuple[float, float]], is_buy: bool,
                  ent: float, sl: float, tp: float) -> int:
    """Port of Pine's ``f_ltfEntryHit`` — resolve the entry (limit-fill) bar.

    Finds the sub-bar where the limit order fills, then only counts a *proven*
    post-fill SL/TP touch. A TP touch in the very fill sub-bar is ignored
    (the extremum may have preceded the fill). Returns 0/1/2 as above.
    """
    filled = False
    for h, l in subbars:
        if not filled:
            if (l <= ent) if is_buy else (h >= ent):
                filled = True
                if (l <= sl) if is_buy else (h >= sl):
                    return 1
        else:
            if (l <= sl) if is_buy else (h >= sl):
                return 1
            if (h >= tp) if is_buy else (l <= tp):
                return 2
    return 0


@dataclass
class Candle:
    ts: int          # open time, ms since epoch
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Plan:
    id: int
    is_buy: bool
    break_lvl: Optional[float]
    pb_target: Optional[float]
    top: float
    bot: float
    rng: float
    create_bar: int
    state: int            # 0 = wait break, 1 = wait fill
    any_break: bool       # break-either-way (Mode B)
    ptype: int            # 0 = pullback, 1 = mid-level
    origin_ts: int
    armed: bool = False   # ARM event already emitted (live)
    # Filled-in when armed:
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    one_r: Optional[float] = None
    trr: Optional[float] = None


@dataclass
class OpenTrade:
    id: int
    is_buy: bool
    entry: float
    sl: float
    tp: float
    bar_idx: int
    one_r: float          # 1R ruler distance (for R accounting & sizing)
    trr: float
    origin_ts: int
    ptype: int


@dataclass
class ClosedTrade:
    is_buy: bool
    entry: float
    sl: float
    tp: float
    is_win: bool
    r: float              # realised R (win -> +trr, loss -> -(|ent-sl|/oneR))
    close_pts: float
    origin_ts: int
    close_ts: int
    ptype: int            # 0 pullback, 1 mid


def one_r_dist_of(cfg: Config, rng: float, atr_val: float) -> float:
    b = cfg.strategy.one_r_basis
    if b == "Distance":
        return cfg.strategy.one_r_dist_fix
    if b == "ATR":
        return atr_val * cfg.strategy.one_r_atr_mult
    return rng * (cfg.strategy.one_r_pct_val / 100.0)


def compute_trade_levels(cfg: Config, plan: Plan, atr_val: float):
    """Return (entry, sl, tp, one_r, trr) exactly as Pine computes at fill."""
    s = cfg.strategy
    isB = plan.is_buy
    rng = plan.rng
    top = plan.top
    bot = plan.bot
    pbT = plan.pb_target
    ent = pbT + (s.spread_pts if isB else -s.spread_pts)

    if plan.ptype == 1:  # mid-level
        if s.mid_sl_mode == "Box Edge":
            slp = bot if isB else top
        else:
            slp = ent - rng * (s.mid_sl_pct / 100.0) if isB else ent + rng * (s.mid_sl_pct / 100.0)
        one_r = abs(ent - slp)
        sl = slp
        tp_edge = top if isB else bot
        if s.mid_tp_mode == "Box Edge":
            tp = tp_edge
        elif s.mid_tp_mode == "R:R Ratio":
            tp = ent + one_r * s.mid_rr if isB else ent - one_r * s.mid_rr
        else:  # % of Box
            tp = ent + rng * (s.mid_tp_pct / 100.0) if isB else ent - rng * (s.mid_tp_pct / 100.0)
    else:  # pullback
        one_r = one_r_dist_of(cfg, rng, atr_val)
        if s.sl_edge_mode:
            sl = bot if isB else top
        else:
            sl = ent - one_r if isB else ent + one_r
        tp = ent + one_r * s.rr_ratio if isB else ent - one_r * s.rr_ratio

    trr = abs(tp - ent) / one_r if one_r > 0 else 0.0
    return ent, sl, tp, one_r, trr


class StrategyEngine:
    def __init__(self, cfg: Config, simulate_fills: bool = True,
                ltf_provider: Optional[LtfProviderT] = None):
        self.cfg = cfg
        self.simulate_fills = simulate_fills
        # Optional callable(parent_ts_ms) -> [(high, low), ...] | None, mirroring
        # Pine's request.security_lower_tf intrabar check (useLtf). When unset,
        # ambiguous same-bar TP/SL touches fall back to Pine's own pessimistic
        # no-intrabar-data behaviour.
        self.ltf_provider = ltf_provider

        # rolling series
        self.highs: List[float] = []
        self.lows: List[float] = []
        self.opens: List[float] = []
        self.closes: List[float] = []
        self.vols: List[float] = []
        self.times: List[int] = []
        self._atr: List[float] = []
        self.bar_index: int = -1

        # swing state
        self.prev_swing_lo: Optional[float] = None
        self.last_swing_lo: Optional[float] = None
        self.prev_swing_hi: Optional[float] = None
        self.last_swing_hi: Optional[float] = None
        self.seq: List[Optional[str]] = [None, None, None]   # seq1, seq2, seq3
        self.seq_px: List[Optional[float]] = [None, None, None]
        self.seq_br: List[Optional[int]] = [None, None, None]

        self.plans: List[Plan] = []
        self.open_trades: List[OpenTrade] = []
        self.closed_trades: List[ClosedTrade] = []
        self._next_id = 1

    # ------------------------------------------------------------------
    def _dow_name(self, ts_ms: int) -> str:
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc) + timedelta(
            hours=self.cfg.strategy.tz_offset_hours
        )
        # Python isoweekday: Mon=1..Sun=7 -> Pine dow Sun=1..Sat=7 -> our name index
        idx = dt.isoweekday() % 7  # Sun->0, Mon->1, ... Sat->6
        return DAY_NAMES[idx]

    def _atr_at(self, i: int) -> float:
        if 0 <= i < len(self._atr):
            v = self._atr[i]
            return v if v == v else 0.0  # NaN guard
        return 0.0

    # ------------------------------------------------------------------
    def process_candle(self, c: Candle) -> List[Dict[str, Any]]:
        """Feed one confirmed candle.  Returns a list of events (live mode)."""
        self.highs.append(c.high)
        self.lows.append(c.low)
        self.opens.append(c.open)
        self.closes.append(c.close)
        self.vols.append(c.volume)
        self.times.append(c.ts)
        self.bar_index += 1
        # ATR recomputed incrementally-ish (cheap for our history sizes)
        self._atr = atr_series(self.highs, self.lows, self.closes, self.cfg.strategy.one_r_atr_period)

        events: List[Dict[str, Any]] = []
        self._detect_swings_and_patterns(events)
        self._run_plan_state_machine(events)
        if self.simulate_fills:
            self._resolve_trades()
        return events

    # ------------------------------------------------------------------
    def _push_seq(self, label: str, px: float, br: int):
        self.seq[0], self.seq_px[0], self.seq_br[0] = self.seq[1], self.seq_px[1], self.seq_br[1]
        self.seq[1], self.seq_px[1], self.seq_br[1] = self.seq[2], self.seq_px[2], self.seq_br[2]
        self.seq[2], self.seq_px[2], self.seq_br[2] = label, px, br

    def _detect_swings_and_patterns(self, events: List[Dict[str, Any]]):
        s = self.cfg.strategy
        L = s.dow_swing_len
        center = self.bar_index - L
        new_buy = False
        new_sell = False
        box_top: Optional[float] = None
        box_bot: Optional[float] = None
        box_left: Optional[int] = None

        piv_hi = pivot_high(self.highs, center, L, L) if center >= 0 else None
        piv_lo = pivot_low(self.lows, center, L, L) if center >= 0 else None

        # --- Swing High ---
        if piv_hi is not None:
            self.prev_swing_hi = self.last_swing_hi
            self.last_swing_hi = piv_hi
            is_hh = self.prev_swing_hi is not None and self.last_swing_hi > self.prev_swing_hi
            is_lh = self.prev_swing_hi is not None and self.last_swing_hi < self.prev_swing_hi
            if is_hh or is_lh:
                self._push_seq("HH" if is_hh else "LH", piv_hi, center)
                # Buy pattern: (LH|HH) -> LL -> HH
                if self.seq[2] == "HH" and self.seq[1] == "LL" and self.seq[0] in ("LH", "HH"):
                    new_buy = True
                    box_top = self.seq_px[2]
                    box_bot = self.seq_px[1]
                    box_left = self.seq_br[0]

        # --- Swing Low ---
        if piv_lo is not None:
            self.prev_swing_lo = self.last_swing_lo
            self.last_swing_lo = piv_lo
            is_hl = self.prev_swing_lo is not None and self.last_swing_lo > self.prev_swing_lo
            is_ll = self.prev_swing_lo is not None and self.last_swing_lo < self.prev_swing_lo
            if is_hl or is_ll:
                self._push_seq("HL" if is_hl else "LL", piv_lo, center)
                # Sell pattern: (HL|LL) -> HH -> LL
                if self.seq[2] == "LL" and self.seq[1] == "HH" and self.seq[0] in ("HL", "LL"):
                    new_sell = True
                    box_top = self.seq_px[1]
                    box_bot = self.seq_px[2]
                    box_left = self.seq_br[0]

        if (new_buy or new_sell) and box_top is not None and box_bot is not None and box_top > box_bot:
            self._create_plans(new_buy, box_top, box_bot, int(box_left), events)

    # ------------------------------------------------------------------
    def _create_plans(self, is_buy_pat: bool, top: float, bot: float, left: int,
                      events: List[Dict[str, Any]]):
        s = self.cfg.strategy
        rng = top - bot
        ts = self.times[self.bar_index]
        day = self._dow_name(ts)
        trade_allowed = s.trade_days.get(day, False)
        mid_only_mode = s.use_mid_level and s.mid_only

        if not trade_allowed:
            events.append({"type": "PATTERN", "note": "no-trade-day", "day": day, "ts": ts})
        elif not mid_only_mode and s.break_either_way:
            # Mode B: neutral range plan
            self._add_plan(Plan(
                id=self._new_id(), is_buy=False, break_lvl=None, pb_target=None,
                top=top, bot=bot, rng=rng, create_bar=self.bar_index, state=0,
                any_break=True, ptype=0, origin_ts=ts))
        elif not mid_only_mode:
            # Mode A: direction fixed by pattern
            break_lvl = top if is_buy_pat else bot
            if s.pullback_mode == "% of Range":
                pb_dist = rng * (s.pullback_range_pct / 100.0)
            else:
                pb_dist = break_lvl * (s.pullback_pct / 100.0)
            pb_target = top - pb_dist if is_buy_pat else bot + pb_dist
            self._add_plan(Plan(
                id=self._new_id(), is_buy=is_buy_pat, break_lvl=break_lvl, pb_target=pb_target,
                top=top, bot=bot, rng=rng, create_bar=self.bar_index, state=0,
                any_break=False, ptype=0, origin_ts=ts))

        # --- Mid-level parallel entry ---
        if s.use_mid_level and trade_allowed:
            make_mid = False
            mid_buy = False
            mid_ent: Optional[float] = None
            close = self.closes[self.bar_index]
            if s.mid_dual_side:
                pct = min(s.mid_entry_pct, 50.0)
                buy_lvl = top - rng * (pct / 100.0)
                sell_lvl = bot + rng * (pct / 100.0)
                can_buy = close > buy_lvl
                can_sell = close < sell_lvl
                if can_buy or can_sell:
                    mid_buy = can_buy
                    mid_ent = buy_lvl if can_buy else sell_lvl
                    make_mid = True
            else:
                mid_buy = is_buy_pat
                mid_ent = (top - rng * (s.mid_entry_pct / 100.0)) if mid_buy else (bot + rng * (s.mid_entry_pct / 100.0))
                make_mid = (close > mid_ent) if mid_buy else (close < mid_ent)
            if make_mid:
                mp = Plan(
                    id=self._new_id(), is_buy=mid_buy, break_lvl=None, pb_target=mid_ent,
                    top=top, bot=bot, rng=rng, create_bar=self.bar_index, state=1,
                    any_break=False, ptype=1, origin_ts=ts)
                self._add_plan(mp)
                # Pine can fill this limit on the very next bar, so in live mode
                # the order must rest from this bar's close — not one bar later.
                if not self.simulate_fills:
                    self._arm(mp, events)

    def _new_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    def _add_plan(self, p: Plan):
        self.plans.append(p)

    # ------------------------------------------------------------------
    def _arm(self, plan: Plan, events: List[Dict[str, Any]]):
        """Compute entry/sl/tp and emit an ARM event (live mode)."""
        ent, sl, tp, one_r, trr = compute_trade_levels(self.cfg, plan, self._atr_at(self.bar_index))
        plan.entry, plan.sl, plan.tp, plan.one_r, plan.trr = ent, sl, tp, one_r, trr
        plan.armed = True
        events.append({
            "type": "ARM", "plan_id": plan.id, "is_buy": plan.is_buy, "ptype": plan.ptype,
            "entry": ent, "sl": sl, "tp": tp, "one_r": one_r, "trr": trr,
            "top": plan.top, "bot": plan.bot, "origin_ts": plan.origin_ts,
        })

    def _cancel_plan(self, plan: Plan, reason: str, events: List[Dict[str, Any]]):
        # Carry the order signature: the plan is removed from ``self.plans``
        # before the executor sees this event, so a plan-id lookup would miss.
        events.append({
            "type": "CANCEL", "plan_id": plan.id, "reason": reason,
            "origin_ts": plan.origin_ts, "ptype": plan.ptype, "is_buy": plan.is_buy,
        })

    def _run_plan_state_machine(self, events: List[Dict[str, Any]]):
        s = self.cfg.strategy
        i = len(self.plans) - 1
        bar = self.bar_index
        high = self.highs[bar]
        low = self.lows[bar]
        while i >= 0:
            p = self.plans[i]
            expired = (bar - p.create_bar) > s.plan_expire_bars
            same_bar = p.create_bar == bar
            remove = False

            if expired:
                if p.armed and not self.simulate_fills:
                    self._cancel_plan(p, "expired", events)
                remove = True
            elif (not same_bar) and p.state == 0 and p.any_break:
                # Mode B: resolve direction on first break
                broke_up = high > p.top
                broke_dn = low < p.bot
                if broke_up or broke_dn:
                    dir_buy = broke_up
                    bl = p.top if dir_buy else p.bot
                    if s.pullback_mode == "% of Range":
                        pbd = p.rng * (s.pullback_range_pct / 100.0)
                    else:
                        pbd = bl * (s.pullback_pct / 100.0)
                    pbt = p.top - pbd if dir_buy else p.bot + pbd
                    p.is_buy = dir_buy
                    p.break_lvl = bl
                    p.pb_target = pbt
                    p.state = 1
                    if not self.simulate_fills:
                        self._arm(p, events)
            elif (not same_bar) and p.state == 0:
                # Mode A: wait for the box edge to break
                broke = (high > p.break_lvl) if p.is_buy else (low < p.break_lvl)
                if broke:
                    p.state = 1
                    if not self.simulate_fills:
                        self._arm(p, events)
            elif (not same_bar) and p.state == 1:
                # State 1: wait fill (pullback or mid).  For mid, cancel if box breaks.
                mid_cancel = False
                if p.ptype == 1:
                    broke_out = (high > p.top) if p.is_buy else (low < p.bot)
                    will_fill = (low <= p.pb_target) if p.is_buy else (high >= p.pb_target)
                    mid_cancel = broke_out and not will_fill
                if mid_cancel:
                    if p.armed and not self.simulate_fills:
                        self._cancel_plan(p, "mid-cancel", events)
                    remove = True
                else:
                    if not p.armed and not self.simulate_fills and p.ptype == 1:
                        # Mid plan arms as soon as it is active (next bar after creation).
                        self._arm(p, events)
                    if self.simulate_fills:
                        reached = (low <= p.pb_target) if p.is_buy else (high >= p.pb_target)
                        if reached:
                            self._open_trade(p)
                            remove = True

            if remove:
                self.plans.pop(i)
            i -= 1

    # ------------------------------------------------------------------
    def _open_trade(self, plan: Plan):
        ent, sl, tp, one_r, trr = compute_trade_levels(self.cfg, plan, self._atr_at(self.bar_index))
        self.open_trades.append(OpenTrade(
            id=plan.id, is_buy=plan.is_buy, entry=ent, sl=sl, tp=tp,
            bar_idx=self.bar_index, one_r=one_r, trr=trr,
            origin_ts=plan.origin_ts, ptype=plan.ptype))

    def _resolve_trades(self):
        """Backtest SL/TP resolution.

        When ``ltf_provider`` is set, ambiguous same-bar touches and the
        entry-fill bar are disambiguated using real intrabar sub-bars, exactly
        like Pine's ``useLtf``. Without a provider (or when it returns no
        data), falls back to Pine's own pessimistic no-intrabar-data rule.
        """
        bar = self.bar_index
        high = self.highs[bar]
        low = self.lows[bar]
        subbars: Optional[List[Tuple[float, float]]] = None
        subbars_fetched = False
        i = len(self.open_trades) - 1
        while i >= 0:
            t = self.open_trades[i]
            if bar >= t.bar_idx:
                hit_sl = (low <= t.sl) if t.is_buy else (high >= t.sl)
                hit_tp = (high >= t.tp) if t.is_buy else (low <= t.tp)
                entry_bar = bar == t.bar_idx
                closed_win = False
                closed_loss = False

                need_ltf = entry_bar or (hit_sl and hit_tp)
                if need_ltf and self.ltf_provider is not None and not subbars_fetched:
                    subbars = self.ltf_provider(self.times[bar])
                    subbars_fetched = True

                if entry_bar:
                    # Fill sub-bar found -> only a proven post-fill SL touch counts;
                    # a bare TP touch on the fill bar is ignored (may precede fill).
                    if subbars:
                        fh = ltf_entry_hit(subbars, t.is_buy, t.entry, t.sl, t.tp)
                        if fh == 1:
                            closed_loss = True
                        elif fh == 2:
                            closed_win = True
                        # fh == 0 -> genuinely unresolved this bar, stays open.
                    elif hit_sl:
                        closed_loss = True
                elif hit_sl and hit_tp:
                    if subbars:
                        fh2 = ltf_first_hit(subbars, t.is_buy, t.sl, t.tp)
                        closed_win = fh2 == 2
                        closed_loss = fh2 != 2
                    else:
                        closed_loss = True  # ambiguous, no intrabar data -> pessimistic
                elif hit_sl:
                    closed_loss = True
                elif hit_tp:
                    closed_win = True

                if closed_win or closed_loss:
                    loss_r = -(abs(t.entry - t.sl) / t.one_r) if t.one_r > 0 else -1.0
                    actual_r = t.trr if closed_win else loss_r
                    close_pts = abs(t.tp - t.entry) if closed_win else abs(t.sl - t.entry)
                    self.closed_trades.append(ClosedTrade(
                        is_buy=t.is_buy, entry=t.entry, sl=t.sl, tp=t.tp,
                        is_win=actual_r > 0, r=actual_r, close_pts=close_pts,
                        origin_ts=t.origin_ts, close_ts=self.times[bar], ptype=t.ptype))
                    self.open_trades.pop(i)
            i -= 1

    # ------------------------------------------------------------------
    # Live-mode helpers (executor drives these)
    # ------------------------------------------------------------------
    def get_plan(self, plan_id: int) -> Optional[Plan]:
        for p in self.plans:
            if p.id == plan_id:
                return p
        return None

    def remove_plan_by_id(self, plan_id: int) -> None:
        self.plans = [p for p in self.plans if p.id != plan_id]

    def remove_plan_by_id_by_sig(self, origin_ts: int, ptype: int, is_buy: bool) -> None:
        """Drop any plan matching a filled order's signature (live mode)."""
        self.plans = [
            p for p in self.plans
            if not (p.origin_ts == origin_ts and p.ptype == ptype and p.is_buy == is_buy)
        ]

    def armed_plans(self) -> List[Plan]:
        return [p for p in self.plans if p.armed]
