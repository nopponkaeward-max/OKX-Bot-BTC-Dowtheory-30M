"""Command-line entry point.

Usage:
    python -m bot.main run       [--config config.yaml]   # dry-run or live loop
    python -m bot.main backtest  [--config config.yaml] [--bars 1500] [--verbose]
    python -m bot.main config    [--config config.yaml]   # print resolved config
"""

from __future__ import annotations

import argparse
import json
import sys

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:  # pragma: no cover
    pass

from .config import load_config
from .okx_client import OKXClient
from . import data as datamod
from . import backtest as bt
from .runner import Runner


def cmd_run(args):
    cfg = load_config(args.config)
    Runner(cfg).run()


def cmd_backtest(args):
    cfg = load_config(args.config)
    client = OKXClient(
        api_key=cfg.exchange.api_key, api_secret=cfg.exchange.api_secret,
        passphrase=cfg.exchange.passphrase, demo=cfg.exchange.demo,
        base_url=cfg.exchange.base_url)
    print(f"Fetching {args.bars} bars of {cfg.exchange.inst_id} {cfg.exchange.bar} ...")
    candles = datamod.fetch_history(client, cfg.exchange.inst_id, cfg.exchange.bar, args.bars)
    print(f"Got {len(candles)} bars. Running backtest ...\n")
    eng = bt.run_backtest(cfg, candles, verbose=args.verbose)
    print("\n" + bt.summary(eng, tz_offset=cfg.strategy.tz_offset_hours,
                             months=args.months))
    print(f"\nClosed trades: {len(eng.closed_trades)} | "
          f"open: {len(eng.open_trades)} | pending plans: {len(eng.plans)}")


def cmd_config(args):
    cfg = load_config(args.config)
    d = cfg.to_dict()
    # redact secrets
    for k in ("api_key", "api_secret", "passphrase"):
        if d["exchange"].get(k):
            d["exchange"][k] = "***"
    print(json.dumps(d, indent=2))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bot", description="DowTheoryBreak OKX bot")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="run dry-run or live loop")
    pr.add_argument("--config", default="config.yaml")
    pr.set_defaults(func=cmd_run)

    pb = sub.add_parser("backtest", help="backtest over history")
    pb.add_argument("--config", default="config.yaml")
    pb.add_argument("--bars", type=int, default=1500)
    pb.add_argument("--months", type=int, default=8)
    pb.add_argument("--verbose", action="store_true")
    pb.set_defaults(func=cmd_backtest)

    pc = sub.add_parser("config", help="print resolved config")
    pc.add_argument("--config", default="config.yaml")
    pc.set_defaults(func=cmd_config)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
