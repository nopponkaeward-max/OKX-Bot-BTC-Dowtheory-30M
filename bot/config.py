"""Configuration for the DowTheoryBreak bot.

Every trading-relevant Pine input is represented here.  Pure-visual inputs
(volume profile, on-chart tables, label sizes) have no meaning for a headless
bot and are omitted; their statistical outputs are reproduced by ``stats.py``.

Values are loaded from a YAML file and can be overridden by environment
variables for secrets.  Call :func:`load_config`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

try:  # optional dependency
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


# --------------------------------------------------------------------------
# Strategy parameters (mirror the Pine "INPUT SETTINGS" section)
# --------------------------------------------------------------------------
@dataclass
class StrategyConfig:
    # --- Swing Pattern ---
    dow_swing_len: int = 3                 # Swing Length (bars left-right)

    # --- Entry Strategy (Pullback %) ---
    pullback_mode: str = "% of Range"      # "% of Range" | "% of Price"
    pullback_range_pct: float = 25.0       # [% of Range] pullback %
    pullback_pct: float = 0.4              # [% of Price] pullback %
    plan_expire_bars: int = 100            # cancel plan if not filled in N bars
    break_either_way: bool = False         # neutral range, direction on break

    # --- Trade Days (True = allowed).  Keys: sun..sat ---
    trade_days: Dict[str, bool] = field(default_factory=lambda: {
        "sun": False, "mon": False, "tue": True, "wed": True,
        "thu": True, "fri": True, "sat": False,
    })

    # --- Mid-Level Entry (parallel) ---
    use_mid_level: bool = True
    mid_only: bool = False                 # trade mid-level only (no pullback)
    mid_dual_side: bool = False            # ignore pattern direction
    mid_entry_pct: float = 25.0            # entry level % from momentum edge
    mid_sl_mode: str = "% of Box"          # "Box Edge" | "% of Box"
    mid_sl_pct: float = 50.0               # [% of Box] SL %
    mid_tp_mode: str = "R:R Ratio"         # "Box Edge" | "R:R Ratio" | "% of Box"
    mid_rr: float = 1.0                    # [R:R Ratio] R:R
    mid_tp_pct: float = 100.0              # [% of Box] TP %

    # --- Risk Management ---
    one_r_basis: str = "SL%"               # "SL%" | "Distance" | "ATR"
    one_r_pct_val: float = 25.0            # [SL%] 1R = % of box range
    one_r_dist_fix: float = 5.0            # [Distance] fixed distance (price)
    one_r_atr_period: int = 14
    one_r_atr_mult: float = 1.5
    sl_edge_mode: bool = False             # SL at opposite box edge
    rr_ratio: float = 1.0                  # Risk : Reward for pullback trades
    spread_pts: float = 0.0                # spread (price units)

    # --- Intrabar check (Lower TF) --- mirrors Pine's useLtf / ltfTf.
    # Disambiguates same-bar TP/SL touches and entry-fill-bar sequencing using
    # real lower-timeframe candles. Backtest-only (live TP/SL is enforced by
    # OKX's own attached orders, which already resolve this correctly).
    use_ltf: bool = True
    ltf_bar: str = "1m"

    # --- Timezone (used for the trade-day filter & stats bucketing) ---
    tz_offset_hours: int = 0               # UTC(+/-); use_exchange -> ignored

    def validate(self) -> None:
        assert 2 <= self.dow_swing_len <= 10, "dow_swing_len must be 2..10"
        assert self.pullback_mode in ("% of Range", "% of Price")
        assert self.one_r_basis in ("SL%", "Distance", "ATR")
        assert self.mid_sl_mode in ("Box Edge", "% of Box")
        assert self.mid_tp_mode in ("Box Edge", "R:R Ratio", "% of Box")
        for k in ("sun", "mon", "tue", "wed", "thu", "fri", "sat"):
            assert k in self.trade_days, f"trade_days missing '{k}'"


# --------------------------------------------------------------------------
# Money / position sizing
# --------------------------------------------------------------------------
@dataclass
class SizingConfig:
    # Real crypto sizing: contracts sized so that a stop-out loses ~risk_usdt.
    #   qty_btc = risk_usdt / |entry - sl|      (USD risk / USD move per BTC)
    #   contracts = qty_btc / ct_val            (rounded to lot size)
    risk_usdt: float = 50.0                # risk per 1R in USDT
    ct_val: float = 0.01                   # BTC per contract (OKX BTC-USDT-SWAP)
    min_contracts: float = 1.0             # OKX minimum order size (contracts)
    lot_size: float = 1.0                  # contract step size
    tick_size: float = 0.1                 # price tick (auto-read from exchange)
    max_contracts: float = 0.0             # 0 = no cap
    leverage: int = 5                      # leverage to set on the instrument
    td_mode: str = "cross"                 # "cross" | "isolated"
    # Legacy Pine sizing (kept for reference / parity backtests only)
    pip_value_ratio: float = 100.0
    use_pine_sizing: bool = False          # if True, size = risk/(oneR*pip_value_ratio)


# --------------------------------------------------------------------------
# Exchange / runtime
# --------------------------------------------------------------------------
@dataclass
class ExchangeConfig:
    inst_id: str = "BTC-USDT-SWAP"
    bar: str = "30m"
    api_key: str = ""
    api_secret: str = ""
    passphrase: str = ""
    demo: bool = True                      # OKX demo trading (x-simulated-trading)
    base_url: str = "https://www.okx.com"
    hedge_mode: bool = False               # position mode (long/short posSide)


@dataclass
class RuntimeConfig:
    mode: str = "dry-run"                  # "dry-run" | "live"
    poll_seconds: int = 20                 # loop cadence
    candle_history: int = 300              # bars to fetch each cycle
    state_file: str = "state/bot_state.json"
    log_file: str = "logs/bot.log"
    log_level: str = "INFO"


@dataclass
class Config:
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    sizing: SizingConfig = field(default_factory=SizingConfig)
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)

    def validate(self) -> None:
        self.strategy.validate()
        assert self.runtime.mode in ("dry-run", "live")

    def to_dict(self) -> dict:
        return asdict(self)


def _apply(dc, data: Optional[dict]):
    if not data:
        return dc
    for k, v in data.items():
        if hasattr(dc, k):
            setattr(dc, k, v)
    return dc


def load_config(path: Optional[str] = None) -> Config:
    """Load config from YAML (if present) then overlay secrets from env."""
    cfg = Config()
    data: dict = {}
    if path and os.path.exists(path):
        if yaml is None:
            raise RuntimeError("PyYAML is required to read config files")
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}

    _apply(cfg.strategy, data.get("strategy"))
    _apply(cfg.sizing, data.get("sizing"))
    _apply(cfg.exchange, data.get("exchange"))
    _apply(cfg.runtime, data.get("runtime"))

    # Secrets / mode from environment always win.
    env = os.environ
    cfg.exchange.api_key = env.get("OKX_API_KEY", cfg.exchange.api_key)
    cfg.exchange.api_secret = env.get("OKX_API_SECRET", cfg.exchange.api_secret)
    cfg.exchange.passphrase = env.get("OKX_PASSPHRASE", cfg.exchange.passphrase)
    if "OKX_DEMO" in env:
        cfg.exchange.demo = env["OKX_DEMO"].strip().lower() in ("1", "true", "yes", "on")
    if "BOT_MODE" in env:
        cfg.runtime.mode = env["BOT_MODE"].strip()

    cfg.validate()
    return cfg
