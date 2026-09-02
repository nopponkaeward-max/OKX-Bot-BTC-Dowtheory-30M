"""Minimal OKX v5 REST client (market data + trading).

Supports live and demo (paper) trading.  Demo mode sends the
``x-simulated-trading: 1`` header against the same host, per OKX docs.

Only the endpoints the bot needs are implemented.  Private calls are signed
with HMAC-SHA256 as required by the v5 API.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests


class OKXError(RuntimeError):
    def __init__(self, code: str, msg: str, payload: Any = None):
        super().__init__(f"OKX error {code}: {msg}")
        self.code = code
        self.msg = msg
        self.payload = payload


class OKXClient:
    def __init__(self, api_key: str = "", api_secret: str = "", passphrase: str = "",
                 demo: bool = True, base_url: str = "https://www.okx.com",
                 timeout: int = 15):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.demo = demo
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()

    # ------------------------------------------------------------------
    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
            f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"

    def _sign(self, ts: str, method: str, path: str, body: str) -> str:
        msg = f"{ts}{method}{path}{body}"
        mac = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()

    def _headers(self, method: str, path: str, body: str, private: bool) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.demo:
            headers["x-simulated-trading"] = "1"
        if private:
            ts = self._timestamp()
            headers.update({
                "OK-ACCESS-KEY": self.api_key,
                "OK-ACCESS-SIGN": self._sign(ts, method, path, body),
                "OK-ACCESS-TIMESTAMP": ts,
                "OK-ACCESS-PASSPHRASE": self.passphrase,
            })
        return headers

    def _request(self, method: str, path: str, params: Optional[dict] = None,
                 body: Optional[dict] = None, private: bool = False,
                 retries: int = 3) -> List[dict]:
        query = ""
        if params:
            query = "?" + urlencode(params)
        req_path = path + query
        body_str = json.dumps(body) if body else ""
        url = self.base_url + req_path

        last_exc: Optional[Exception] = None
        for attempt in range(retries):
            try:
                headers = self._headers(method, req_path, body_str, private)
                resp = self._session.request(
                    method, url, headers=headers,
                    data=body_str if body_str else None, timeout=self.timeout)
                data = resp.json()
                if str(data.get("code")) != "0":
                    # Order-level errors surface here too; raise with detail.
                    raise OKXError(str(data.get("code")), data.get("msg", ""), data)
                return data.get("data", [])
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                time.sleep(2 ** attempt)
        raise OKXError("network", str(last_exc))

    # ------------------------------------------------------------------
    # Public market data
    # ------------------------------------------------------------------
    def get_candles(self, inst_id: str, bar: str = "30m", limit: int = 300,
                    history: bool = False, after: Optional[int] = None,
                    before: Optional[int] = None) -> List[List[str]]:
        """Return raw candles newest-first: [ts, o, h, l, c, vol, ...].

        ``after``  = only return candles with ts strictly earlier than this (OKX semantics).
        ``before`` = only return candles with ts strictly later than this (OKX semantics).
        """
        path = "/api/v5/market/history-candles" if history else "/api/v5/market/candles"
        params: Dict[str, Any] = {"instId": inst_id, "bar": bar, "limit": limit}
        if after is not None:
            params["after"] = str(after)
        if before is not None:
            params["before"] = str(before)
        return self._request("GET", path, params=params)

    def get_ticker(self, inst_id: str) -> dict:
        data = self._request("GET", "/api/v5/market/ticker", params={"instId": inst_id})
        return data[0] if data else {}

    def get_instrument(self, inst_id: str, inst_type: str = "SWAP") -> dict:
        data = self._request("GET", "/api/v5/public/instruments",
                             params={"instType": inst_type, "instId": inst_id})
        return data[0] if data else {}

    # ------------------------------------------------------------------
    # Account / trading (private)
    # ------------------------------------------------------------------
    def get_balance(self, ccy: str = "USDT") -> dict:
        data = self._request("GET", "/api/v5/account/balance",
                             params={"ccy": ccy}, private=True)
        return data[0] if data else {}

    def set_leverage(self, inst_id: str, lever: int, mgn_mode: str = "cross",
                     pos_side: Optional[str] = None) -> List[dict]:
        body = {"instId": inst_id, "lever": str(lever), "mgnMode": mgn_mode}
        if pos_side:
            body["posSide"] = pos_side
        return self._request("POST", "/api/v5/account/set-leverage", body=body, private=True)

    def place_order(self, order: Dict[str, Any]) -> dict:
        data = self._request("POST", "/api/v5/trade/order", body=order, private=True)
        return data[0] if data else {}

    def cancel_order(self, inst_id: str, ord_id: Optional[str] = None,
                     cl_ord_id: Optional[str] = None) -> dict:
        body: Dict[str, str] = {"instId": inst_id}
        if ord_id:
            body["ordId"] = ord_id
        if cl_ord_id:
            body["clOrdId"] = cl_ord_id
        data = self._request("POST", "/api/v5/trade/cancel-order", body=body, private=True)
        return data[0] if data else {}

    def get_order(self, inst_id: str, ord_id: Optional[str] = None,
                  cl_ord_id: Optional[str] = None) -> dict:
        params: Dict[str, str] = {"instId": inst_id}
        if ord_id:
            params["ordId"] = ord_id
        if cl_ord_id:
            params["clOrdId"] = cl_ord_id
        data = self._request("GET", "/api/v5/trade/order", params=params, private=True)
        return data[0] if data else {}

    def get_pending_orders(self, inst_id: str) -> List[dict]:
        return self._request("GET", "/api/v5/trade/orders-pending",
                             params={"instId": inst_id}, private=True)

    def get_positions(self, inst_id: str) -> List[dict]:
        return self._request("GET", "/api/v5/account/positions",
                             params={"instId": inst_id}, private=True)
