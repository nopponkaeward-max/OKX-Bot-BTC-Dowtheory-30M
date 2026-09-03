"""Translate engine ARM/CANCEL events into real OKX orders (live mode).

Design
------
* An ARM event means "a limit order should now rest on the exchange at the
  computed entry, protected by attached TP/SL".  We place it once, keyed by a
  stable signature so restarts never double-place.
* A CANCEL event (expiry / mid-cancel) cancels the resting order if unfilled.
* Fills are detected by polling order status; a filled entry becomes a live
  trade whose TP/SL are managed by OKX's attached algo orders.  For statistics
  we mirror the indicator's win/loss accounting on closed bars.

All exchange state is reconciled defensively, and every order action is logged.
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

from .config import Config
from .engine import Candle, Plan, StrategyEngine, ClosedTrade
from .okx_client import OKXClient, OKXError

log = logging.getLogger("bot.executor")


def size_contracts(cfg: Config, one_r: float) -> float:
    s = cfg.sizing
    if one_r <= 0:
        return 0.0
    if s.use_pine_sizing:
        qty = s.risk_usdt / (one_r * s.pip_value_ratio)
    else:
        qty_btc = s.risk_usdt / one_r        # USD risk / USD move-per-BTC = BTC
        qty = qty_btc / s.ct_val             # -> contracts
    if s.lot_size > 0:
        # Floor to the lot step: rounding up would risk more than risk_usdt.
        qty = math.floor(qty / s.lot_size + 1e-9) * s.lot_size
    qty = max(qty, s.min_contracts)
    if s.max_contracts > 0:
        qty = min(qty, s.max_contracts)
    return round(qty, 8)


def quantize_str(value: float, step: float) -> str:
    """Quantize ``value`` to a multiple of ``step`` (exchange tick/lot size)
    and render it as a plain decimal string (never scientific notation)."""
    if step <= 0:
        return format(Decimal(str(value)).normalize(), "f")
    d = (Decimal(str(value)) / Decimal(str(step))).to_integral_value(rounding=ROUND_HALF_UP)
    return format((d * Decimal(str(step))).normalize(), "f")


def _sig(plan: Plan, entry: float) -> str:
    return f"{plan.origin_ts}-{plan.ptype}-{int(plan.is_buy)}-{round(entry, 1)}"


def _cl_ord_id(plan: Plan, entry: float) -> str:
    tag = f"dt{str(plan.origin_ts)[-10:]}{plan.ptype}{'b' if plan.is_buy else 's'}"
    return tag[:32]


@dataclass
class OrderRec:
    sig: str
    cl_ord_id: str
    ord_id: str
    is_buy: bool
    entry: float
    sl: float
    tp: float
    one_r: float
    trr: float
    ptype: int
    origin_ts: int
    size: float
    status: str = "placed"   # placed | filled | closed | cancelled


class Executor:
    def __init__(self, cfg: Config, client: OKXClient, engine: StrategyEngine):
        self.cfg = cfg
        self.client = client
        self.engine = engine
        self.orders: Dict[str, OrderRec] = {}       # sig -> record
        self.closed: List[ClosedTrade] = []
        self._lev_set = False
        self._load_instrument()

    # ------------------------------------------------------------------
    def _load_instrument(self):
        try:
            inst = self.client.get_instrument(self.cfg.exchange.inst_id)
            if inst:
                self.cfg.sizing.ct_val = float(inst.get("ctVal", self.cfg.sizing.ct_val))
                self.cfg.sizing.lot_size = float(inst.get("lotSz", self.cfg.sizing.lot_size))
                self.cfg.sizing.min_contracts = float(inst.get("minSz", self.cfg.sizing.min_contracts))
                self.cfg.sizing.tick_size = float(inst.get("tickSz", self.cfg.sizing.tick_size))
                log.info("Instrument %s: ctVal=%s lotSz=%s minSz=%s tickSz=%s",
                         self.cfg.exchange.inst_id, inst.get("ctVal"),
                         inst.get("lotSz"), inst.get("minSz"), inst.get("tickSz"))
        except OKXError as e:
            log.warning("Could not load instrument spec: %s", e)

    def _ensure_leverage(self):
        if self._lev_set:
            return
        try:
            self.client.set_leverage(self.cfg.exchange.inst_id, self.cfg.sizing.leverage,
                                     self.cfg.sizing.td_mode)
            self._lev_set = True
        except OKXError as e:
            log.warning("set_leverage failed (continuing): %s", e)

    # ------------------------------------------------------------------
    def handle_events(self, events: List[Dict], act: bool):
        """Process engine events for one bar.  ``act=False`` during warmup."""
        for ev in events:
            if ev["type"] == "ARM" and act:
                self._place_entry(ev)
            elif ev["type"] == "CANCEL" and act:
                self._cancel_by_event(ev)

    def _place_entry(self, ev: Dict):
        tick = self.cfg.sizing.tick_size
        # OKX rejects prices that are not a multiple of the instrument tick size.
        entry_s = quantize_str(ev["entry"], tick)
        sl_s = quantize_str(ev["sl"], tick)
        tp_s = quantize_str(ev["tp"], tick)
        entry, sl, tp = float(entry_s), float(sl_s), float(tp_s)

        class _P:  # minimal shim for signature helpers
            origin_ts = ev["origin_ts"]
            ptype = ev["ptype"]
            is_buy = ev["is_buy"]
        sig = _sig(_P, entry)  # type: ignore[arg-type]
        if sig in self.orders and self.orders[sig].status in ("placed", "filled"):
            return  # already live
        size = size_contracts(self.cfg, ev["one_r"])
        if size <= 0:
            log.warning("Computed size 0 for plan %s; skipping", ev["plan_id"])
            return
        self._ensure_leverage()
        cl = _cl_ord_id(_P, entry)  # type: ignore[arg-type]
        order = {
            "instId": self.cfg.exchange.inst_id,
            "tdMode": self.cfg.sizing.td_mode,
            "clOrdId": cl,
            "side": "buy" if ev["is_buy"] else "sell",
            "ordType": "limit",
            "px": entry_s,
            "sz": quantize_str(size, 0),
            "attachAlgoOrds": [{
                "tpTriggerPx": tp_s,
                "tpOrdPx": "-1",
                "slTriggerPx": sl_s,
                "slOrdPx": "-1",
                "tpTriggerPxType": "last",
                "slTriggerPxType": "last",
            }],
        }
        if self.cfg.exchange.hedge_mode:
            order["posSide"] = "long" if ev["is_buy"] else "short"
        try:
            res = self.client.place_order(order)
            ord_id = res.get("ordId", "")
            self.orders[sig] = OrderRec(
                sig=sig, cl_ord_id=cl, ord_id=ord_id, is_buy=ev["is_buy"],
                entry=entry, sl=sl, tp=tp, one_r=ev["one_r"],
                trr=ev["trr"], ptype=ev["ptype"], origin_ts=ev["origin_ts"], size=size)
            log.info("PLACED %s %s limit @%s sz=%s SL=%s TP=%s (ord %s)",
                     "BUY" if ev["is_buy"] else "SELL",
                     "MID" if ev["ptype"] == 1 else "PB", entry_s, size,
                     sl_s, tp_s, ord_id or cl)
        except OKXError as e:
            log.error("place_order failed for plan %s: %s", ev["plan_id"], e)
            self._adopt_existing(sig, cl, ev, entry, sl, tp, size)

    def _adopt_existing(self, sig: str, cl: str, ev: Dict,
                        entry: float, sl: float, tp: float, size: float):
        """Recover an order OKX already holds under our clOrdId.

        Happens when a place request timed out but was accepted (the retry is
        then rejected as a duplicate clOrdId), or when local state was lost
        across a restart.  Without adopting it, every cycle would re-fail while
        an untracked order rests on the exchange."""
        try:
            info = self.client.get_order(self.cfg.exchange.inst_id, cl_ord_id=cl)
        except OKXError:
            return
        state = info.get("state")
        if state not in ("live", "partially_filled", "filled"):
            return
        self.orders[sig] = OrderRec(
            sig=sig, cl_ord_id=cl, ord_id=info.get("ordId", ""), is_buy=ev["is_buy"],
            entry=float(info.get("avgPx") or entry), sl=sl, tp=tp,
            one_r=ev["one_r"], trr=ev["trr"], ptype=ev["ptype"],
            origin_ts=ev["origin_ts"], size=size,
            status="filled" if state == "filled" else "placed")
        if state == "filled":
            self.engine.remove_plan_by_id_by_sig(ev["origin_ts"], ev["ptype"], ev["is_buy"])
        log.info("ADOPTED existing order %s (state=%s)", cl, state)

    def _cancel_by_event(self, ev: Dict):
        """Cancel resting orders matching the cancelled plan's signature.

        The engine drops the plan from its list before this event is handled,
        so matching must use the (origin_ts, ptype, is_buy) carried in the
        event — a plan-id lookup would always miss."""
        for rec in self.orders.values():
            if rec.status == "placed" and rec.origin_ts == ev.get("origin_ts") \
                    and rec.ptype == ev.get("ptype") and rec.is_buy == ev.get("is_buy"):
                self._cancel_order(rec)

    def _cancel_order(self, rec: OrderRec):
        try:
            self.client.cancel_order(self.cfg.exchange.inst_id, cl_ord_id=rec.cl_ord_id)
            rec.status = "cancelled"
            log.info("CANCELLED %s (%s)", rec.cl_ord_id, rec.ord_id)
        except OKXError as e:
            log.warning("cancel_order failed for %s: %s (may be filled)", rec.cl_ord_id, e)

    # ------------------------------------------------------------------
    def poll_fills(self):
        """Check resting orders for fills; promote them to live trades."""
        for rec in list(self.orders.values()):
            if rec.status != "placed":
                continue
            try:
                info = self.client.get_order(self.cfg.exchange.inst_id, cl_ord_id=rec.cl_ord_id)
            except OKXError as e:
                log.debug("get_order failed for %s: %s", rec.cl_ord_id, e)
                continue
            state = info.get("state")
            if state == "filled":
                avg = float(info.get("avgPx") or rec.entry)
                rec.entry = avg
                rec.status = "filled"
                # Once filled, drop the engine plan so it is not re-placed.
                self.engine.remove_plan_by_id_by_sig(rec.origin_ts, rec.ptype, rec.is_buy)
                log.info("FILLED %s @%.1f (OKX now managing TP/SL)", rec.cl_ord_id, avg)
            elif state in ("canceled", "cancelled"):
                rec.status = "cancelled"

    def resolve_closed(self, last: Candle):
        """Mirror indicator win/loss accounting for filled trades on closed bars."""
        for rec in list(self.orders.values()):
            if rec.status != "filled":
                continue
            hit_sl = (last.low <= rec.sl) if rec.is_buy else (last.high >= rec.sl)
            hit_tp = (last.high >= rec.tp) if rec.is_buy else (last.low <= rec.tp)
            win = False
            loss = False
            if hit_sl and hit_tp:
                loss = True            # ambiguous -> pessimistic
            elif hit_sl:
                loss = True
            elif hit_tp:
                win = True
            if win or loss:
                loss_r = -(abs(rec.entry - rec.sl) / rec.one_r) if rec.one_r > 0 else -1.0
                r = rec.trr if win else loss_r
                self.closed.append(ClosedTrade(
                    is_buy=rec.is_buy, entry=rec.entry, sl=rec.sl, tp=rec.tp,
                    is_win=r > 0, r=r, close_pts=abs((rec.tp if win else rec.sl) - rec.entry),
                    origin_ts=rec.origin_ts, close_ts=last.ts, ptype=rec.ptype))
                rec.status = "closed"
                log.info("CLOSED %s %s R=%+.2f", rec.cl_ord_id, "WIN" if win else "LOSS", r)

    # ------------------------------------------------------------------
    def state_dict(self) -> dict:
        return {"orders": {k: asdict(v) for k, v in self.orders.items()},
                "closed": [asdict(c) for c in self.closed]}

    def load_state(self, data: dict):
        for k, v in (data.get("orders") or {}).items():
            self.orders[k] = OrderRec(**v)
        for c in (data.get("closed") or []):
            self.closed.append(ClosedTrade(**c))
