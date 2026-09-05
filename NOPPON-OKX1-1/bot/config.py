"""Configuration for the NOPPON-GOLD1-1 Session Breakout bot.

Every trading-relevant Pine input is represented here.  Pure-visual inputs
(box colours, label sizes, table positions) are omitted.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

try:
    import yaml  # type: ignore
except Exception:
    yaml = None


@dataclass
class SessionDef:
    name: str
    enabled: bool
    time_str: str       # "HHMM-HHMM" UTC, Oct-Mar
    dst_time_str: str   # "HHMM-HHMM" UTC, Apr-Sep


@dataclass
class StrategyConfig:
    # --- Entry Strategy ---
    entry_mode: str = "Breakout"    # "Breakout" | "Pullback" | "PBRebreak"
    pullback_range_pct: float = 20.0
    plan_expire_hours: float = 0.0  # 0 = cancel at next session start

    close_main_on_new_ses: bool = True

    # --- 2nd Order ---
    use_2nd_order: bool = True
    use_2nd_custom_rr: bool = False
    second_rr: float = 5.0

    # --- 50% Add-on ---
    use_addon_50: bool = True
    addon_tp_mode: str = "RR"      # "MainCost" | "RR"
    addon_rr: float = 5.0
    addon_main_be: bool = False
    addon_keep_open: bool = False

    # --- Trade Days ---
    trade_days: Dict[str, bool] = field(default_factory=lambda: {
        "sun": False, "mon": True, "tue": True, "wed": True,
        "thu": True, "fri": True, "sat": False,
    })

    # --- Sessions ---
    sessions: List[SessionDef] = field(default_factory=lambda: [
        SessionDef("Sydney", True, "2000-0500", "2100-0600"),
        SessionDef("Tokyo", False, "0000-0900", "0000-0900"),
        SessionDef("London", False, "0800-1700", "0700-1600"),
        SessionDef("NewYork", False, "1300-2200", "1200-2100"),
    ])

    gap_fallback: bool = False
    tz_offset_hours: int = 0

    # --- Risk Management ---
    one_r_basis: str = "SL%"       # "SL%" | "Distance" | "ATR"
    one_r_pct_val: float = 55.0
    one_r_dist_fix: float = 5.0
    one_r_atr_period: int = 14
    one_r_atr_mult: float = 1.5
    sl_edge_mode: bool = False
    rr_ratio: float = 5.0
    rr_base_mode: str = "SLDistance"  # "1RBasis" | "SLDistance"
    risk_amount: float = 500.0
    pip_value_ratio: float = 100.0
    spread_pts: float = 0.0

    # --- Trailing SL ---
    use_trail: bool = False
    trail_trigger_r: float = 2.0
    trail_lock_r: float = 1.0

    def validate(self) -> None:
        assert self.entry_mode in ("Breakout", "Pullback", "PBRebreak")
        assert self.one_r_basis in ("SL%", "Distance", "ATR")
        assert self.rr_base_mode in ("1RBasis", "SLDistance")
        for k in ("sun", "mon", "tue", "wed", "thu", "fri", "sat"):
            assert k in self.trade_days, f"trade_days missing '{k}'"


@dataclass
class SizingConfig:
    risk_usdt: float = 50.0
    ct_val: float = 0.01
    min_contracts: float = 1.0
    lot_size: float = 1.0
    tick_size: float = 0.1
    max_contracts: float = 0.0
    leverage: int = 5
    td_mode: str = "cross"
    pip_value_ratio: float = 100.0
    use_pine_sizing: bool = False


@dataclass
class ExchangeConfig:
    inst_id: str = "BTC-USDT-SWAP"
    bar: str = "30m"
    api_key: str = ""
    api_secret: str = ""
    passphrase: str = ""
    demo: bool = True
    base_url: str = "https://www.okx.com"
    hedge_mode: bool = False


@dataclass
class RuntimeConfig:
    mode: str = "dry-run"
    poll_seconds: int = 20
    candle_history: int = 300
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


def _load_sessions(raw: Optional[list]) -> List[SessionDef]:
    if not raw:
        return StrategyConfig().sessions
    out = []
    for s in raw:
        out.append(SessionDef(
            name=s.get("name", ""),
            enabled=s.get("enabled", False),
            time_str=s.get("time_str", "0000-0000"),
            dst_time_str=s.get("dst_time_str", "0000-0000"),
        ))
    return out


def load_config(path: Optional[str] = None) -> Config:
    cfg = Config()
    data: dict = {}
    if path and os.path.exists(path):
        if yaml is None:
            raise RuntimeError("PyYAML is required to read config files")
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}

    strat_data = data.get("strategy", {})
    if "sessions" in strat_data:
        cfg.strategy.sessions = _load_sessions(strat_data.pop("sessions"))
    _apply(cfg.strategy, strat_data)
    _apply(cfg.sizing, data.get("sizing"))
    _apply(cfg.exchange, data.get("exchange"))
    _apply(cfg.runtime, data.get("runtime"))

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
