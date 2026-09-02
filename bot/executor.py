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
import os
from dataclasses import dataclass, asdict
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
        qty = round(qty / s.lot_size) * s.lot_size
    qty = max(qty, s.min_contracts)
    if s.max_contracts > 0:
        qty = min(qty, s.max_contracts)
    return round(qty, 8)


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
                log.info("Instrument %s: ctVal=%s lotSz=%s minSz=%s",
                         self.cfg.exchange.inst_id, inst.get("ctVal"),
                         inst.get("lotSz"), inst.get("minSz"))
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
                self._cancel_by_plan(ev["plan_id"])

    def _place_entry(self, ev: Dict):
        plan = self.engine.get_plan(ev["plan_id"])
        entry = ev["entry"]
        # Build a synthetic plan-like object for signature helpers
        class _P:  # minimal shim
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
            "px": f"{entry}",
            "sz": f"{size}",
            "attachAlgoOrds": [{
                "tpTriggerPx": f"{ev['tp']}",
                "tpOrdPx": "-1",
                "slTriggerPx": f"{ev['sl']}",
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
                entry=entry, sl=ev["sl"], tp=ev["tp"], one_r=ev["one_r"],
                trr=ev["trr"], ptype=ev["ptype"], origin_ts=ev["origin_ts"], size=size)
            log.info("PLACED %s %s limit @%.1f sz=%s SL=%.1f TP=%.1f (ord %s)",
                     "BUY" if ev["is_buy"] else "SELL",
                     "MID" if ev["ptype"] == 1 else "PB", entry, size,
                     ev["sl"], ev["tp"], ord_id or cl)
        except OKXError as e:
            log.error("place_order failed for plan %s: %s", ev["plan_id"], e)

    def _cancel_by_plan(self, plan_id: int):
        plan = self.engine.get_plan(plan_id)
        # We may not have the plan anymore; try matching by any placed order that
        # is still resting for this origin.  Cancel any 'placed' order not filled.
        for rec in self.orders.values():
            if rec.status == "placed" and plan and rec.origin_ts == plan.origin_ts \
                    and rec.ptype == plan.ptype and rec.is_buy == plan.is_buy:
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
