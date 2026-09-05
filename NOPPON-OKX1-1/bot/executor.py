"""Translate engine events into real OKX orders (live mode).

Design
------
* FILL / FILL_ORDER3 / FILL_ORDER2 events: place limit entry with attached TP/SL.
* CANCEL events: cancel resting orders (OCO partner, expired plan).
* CLOSE_SESSION events: close position at market.
* Fills are detected by polling order status; TP/SL are managed by OKX's
  attached algo orders.

All exchange state is reconciled defensively, and every order action is logged.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

from .config import Config
from .engine import ClosedTrade
from .okx_client import OKXClient, OKXError

log = logging.getLogger("bot.executor")


def size_contracts(cfg: Config, one_r: float, lot: float = 0.0) -> float:
    s = cfg.sizing
    if s.use_pine_sizing and lot > 0:
        return lot
    if one_r <= 0:
        return 0.0
    qty_btc = s.risk_usdt / one_r
    qty = qty_btc / s.ct_val
    if s.lot_size > 0:
        qty = math.floor(qty / s.lot_size + 1e-9) * s.lot_size
    qty = max(qty, s.min_contracts)
    if s.max_contracts > 0:
        qty = min(qty, s.max_contracts)
    return round(qty, 8)


def quantize_str(value: float, step: float) -> str:
    if step <= 0:
        return format(Decimal(str(value)).normalize(), "f")
    d = (Decimal(str(value)) / Decimal(str(step))).to_integral_value(rounding=ROUND_HALF_UP)
    return format((d * Decimal(str(step))).normalize(), "f")


def _sig(ev: Dict) -> str:
    etype = ev.get("type", "FILL")
    side = "b" if ev["is_buy"] else "s"
    return f"{etype}-{ev.get('trade_id', 0)}-{side}-{round(ev['entry'], 1)}"


def _cl_ord_id(ev: Dict) -> str:
    tid = ev.get("trade_id", 0)
    side = "b" if ev["is_buy"] else "s"
    tag = f"sb{tid}{side}{str(int(ev['entry']))[-8:]}"
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
    size: float
    trade_id: int = 0
    status: str = "placed"  # placed | filled | closed | cancelled


class Executor:
    def __init__(self, cfg: Config, client: OKXClient):
        self.cfg = cfg
        self.client = client
        self.orders: Dict[str, OrderRec] = {}
        self.closed: List[ClosedTrade] = []
        self._lev_set = False
        self._load_instrument()

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
            self.client.set_leverage(self.cfg.exchange.inst_id,
                                     self.cfg.sizing.leverage,
                                     self.cfg.sizing.td_mode)
            self._lev_set = True
        except OKXError as e:
            log.warning("set_leverage failed (continuing): %s", e)

    # ------------------------------------------------------------------
    def handle_events(self, events: List[Dict], act: bool):
        for ev in events:
            etype = ev["type"]
            if not act:
                continue
            if etype in ("FILL", "FILL_ORDER3", "FILL_ORDER2"):
                self._place_entry(ev)
            elif etype == "CANCEL":
                self._cancel_by_event(ev)
            elif etype == "CLOSE_SESSION":
                self._close_position(ev)

    def _place_entry(self, ev: Dict):
        tick = self.cfg.sizing.tick_size
        entry_s = quantize_str(ev["entry"], tick)
        sl_s = quantize_str(ev["sl"], tick)
        tp_s = quantize_str(ev["tp"], tick)
        entry = float(entry_s)

        sig = _sig(ev)
        if sig in self.orders and self.orders[sig].status in ("placed", "filled"):
            return

        one_r = ev.get("one_r", abs(ev["entry"] - ev["sl"]))
        size = size_contracts(self.cfg, one_r, ev.get("lot", 0.0))
        if size <= 0:
            log.warning("Computed size 0 for trade %s; skipping", ev.get("trade_id"))
            return

        self._ensure_leverage()
        cl = _cl_ord_id(ev)
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

        _labels = {"FILL": "Order-1", "FILL_ORDER3": "Order-3", "FILL_ORDER2": "Order-2"}
        label = _labels.get(ev["type"], ev["type"])
        try:
            res = self.client.place_order(order)
            ord_id = res.get("ordId", "")
            self.orders[sig] = OrderRec(
                sig=sig, cl_ord_id=cl, ord_id=ord_id, is_buy=ev["is_buy"],
                entry=entry, sl=float(sl_s), tp=float(tp_s), one_r=one_r,
                trr=ev.get("trr", 0.0), size=size, trade_id=ev.get("trade_id", 0))
            log.info("PLACED %s %s limit @%s sz=%s SL=%s TP=%s (ord %s)",
                     label, "BUY" if ev["is_buy"] else "SELL", entry_s, size,
                     sl_s, tp_s, ord_id or cl)
        except OKXError as e:
            log.error("place_order failed for %s: %s", label, e)
            self._adopt_existing(sig, cl, ev, entry, float(sl_s), float(tp_s),
                                 one_r, size)

    def _adopt_existing(self, sig: str, cl: str, ev: Dict,
                        entry: float, sl: float, tp: float,
                        one_r: float, size: float):
        try:
            info = self.client.get_order(self.cfg.exchange.inst_id, cl_ord_id=cl)
        except OKXError:
            return
        state = info.get("state")
        if state not in ("live", "partially_filled", "filled"):
            return
        self.orders[sig] = OrderRec(
            sig=sig, cl_ord_id=cl, ord_id=info.get("ordId", ""),
            is_buy=ev["is_buy"],
            entry=float(info.get("avgPx") or entry), sl=sl, tp=tp,
            one_r=one_r, trr=ev.get("trr", 0.0), size=size,
            trade_id=ev.get("trade_id", 0),
            status="filled" if state == "filled" else "placed")
        log.info("ADOPTED existing order %s (state=%s)", cl, state)

    def _cancel_by_event(self, ev: Dict):
        plan_id = ev.get("plan_id")
        oco_id = ev.get("oco_id")
        for rec in list(self.orders.values()):
            if rec.status != "placed":
                continue
            if oco_id and rec.sig.endswith(str(round(ev.get("entry", 0), 1))):
                self._cancel_order(rec)

    def _cancel_order(self, rec: OrderRec):
        try:
            self.client.cancel_order(self.cfg.exchange.inst_id,
                                     cl_ord_id=rec.cl_ord_id)
            rec.status = "cancelled"
            log.info("CANCELLED %s (%s)", rec.cl_ord_id, rec.ord_id)
        except OKXError as e:
            log.warning("cancel_order failed for %s: %s (may be filled)",
                        rec.cl_ord_id, e)

    def _close_position(self, ev: Dict):
        side = "sell" if ev["is_buy"] else "buy"
        try:
            self.client.close_position(
                self.cfg.exchange.inst_id,
                mgnMode=self.cfg.sizing.td_mode,
                posSide="long" if ev["is_buy"] else "short" if self.cfg.exchange.hedge_mode else "")
            log.info("CLOSED position %s @%.1f R=%+.2f",
                     "BUY" if ev["is_buy"] else "SELL",
                     ev.get("close_px", 0), ev.get("r", 0))
        except OKXError as e:
            log.warning("close_position failed: %s", e)

    # ------------------------------------------------------------------
    def poll_fills(self):
        for rec in list(self.orders.values()):
            if rec.status != "placed":
                continue
            try:
                info = self.client.get_order(self.cfg.exchange.inst_id,
                                             cl_ord_id=rec.cl_ord_id)
            except OKXError as e:
                log.debug("get_order failed for %s: %s", rec.cl_ord_id, e)
                continue
            state = info.get("state")
            if state == "filled":
                avg = float(info.get("avgPx") or rec.entry)
                rec.entry = avg
                rec.status = "filled"
                log.info("FILLED %s @%.1f (OKX managing TP/SL)", rec.cl_ord_id, avg)
            elif state in ("canceled", "cancelled"):
                rec.status = "cancelled"

    # ------------------------------------------------------------------
    def state_dict(self) -> dict:
        return {"orders": {k: asdict(v) for k, v in self.orders.items()},
                "closed": [asdict(c) for c in self.closed]}

    def load_state(self, data: dict):
        for k, v in (data.get("orders") or {}).items():
            self.orders[k] = OrderRec(**v)
        for c in (data.get("closed") or []):
            self.closed.append(ClosedTrade(**c))
