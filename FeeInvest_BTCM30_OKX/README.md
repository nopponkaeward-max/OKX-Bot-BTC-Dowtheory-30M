# DowTheoryBreak — BTC Perp OKX Trading Bot (30m)

A Python trading bot for **BTC-USDT-SWAP on OKX (30-minute)** that faithfully
ports the `DowTheoryBreak_V1.0` TradingView Pine Script strategy. The same pure
strategy engine drives both a **backtester** (reproducing the indicator's
win/loss accounting bar-for-bar) and a **live/dry-run executor** that places real
OKX orders.

> ⚠️ **Trading risk.** This software can place real orders and lose real money.
> It defaults to **dry-run** (no orders) and **OKX demo** trading. Test on demo
> thoroughly before risking funds. No warranty of any kind.

---

## Strategy in a nutshell

1. **Swing detection (Dow Theory)** — pivot highs/lows (`dow_swing_len` bars each
   side) are labelled HH / LH / HL / LL.
2. **Pattern boxes** — a rolling 3-swing sequence forms a box:
   - **Buy**: `(LH|HH) → LL → HH`  (box = HH top … LL bottom)
   - **Sell**: `(HL|LL) → HH → LL` (box = HH top … LL bottom)
3. **Entries** (both can run in parallel):
   - **Pullback %** — wait for price to *break* the box edge, then *pull back*
     X% into the box, then fill a limit order.
   - **Mid-Level** — a limit order placed X% in from the momentum edge, cancelled
     if the box breaks the opposite side before filling.
   - **Break-either-way** — treat the box as a neutral range; direction is decided
     by whichever edge breaks first.
4. **Risk** — 1R sized from box % / fixed distance / ATR; SL at 1R or the opposite
   box edge; TP from R:R ratio, box edge, or box %.
5. **Filters** — per-weekday trade toggles (based on the day the pattern forms).
6. **Stats** — overall, by-day (Sun–Sat) and monthly performance, mirroring the
   indicator's on-chart tables.

---

## What is and isn't ported

| Pine feature | Status in the bot |
|---|---|
| Swing / pattern detection (`ta.pivothigh/low`) | ✅ faithful |
| Pullback %, Mid-Level, Mid-Only, Dual-Side, Break-either-way | ✅ faithful |
| Trade-day filter (Sun–Sat) | ✅ faithful |
| 1R basis: SL% / Distance / ATR, SL-at-edge, R:R, spread, plan expiry, mid-cancel | ✅ faithful |
| Win/Loss + Net R + streaks + by-day + monthly stats | ✅ faithful (headless) |
| Intrabar lower-TF TP/SL sequencing | ➖ stats use closed-bar pessimistic rule; **live TP/SL is enforced by OKX** attached orders |
| Volume Profile, on-chart boxes/labels/tables, daily-log table | ➖ chart-only visuals, not applicable to a headless bot |
| Position sizing | 🔁 real crypto **risk-based** sizing by default (`risk_usdt / stop-distance → contracts`); Pine's forex-style lot available via `use_pine_sizing` |

---

## Layout

```
bot/
  config.py     # all strategy params (mirrors Pine inputs) + YAML/env loading
  indicators.py # pivot high/low, Wilder ATR
  engine.py     # pure bar-for-bar strategy engine (backtest + live share it)
  okx_client.py # OKX v5 REST client (market data + signed trading)
  data.py       # candle fetch/parse/pagination
  executor.py   # ARM/CANCEL events -> real OKX limit + attached TP/SL
  runner.py     # warmup + dry-run/live loop
  stats.py      # overall / by-day / monthly tables
  backtest.py   # historical backtest
  main.py       # CLI
tests/          # unit + integration tests
config.yaml     # editable defaults
```

---

## Setup

All commands below assume you're inside this folder:
```bash
cd FeeInvest_BTCM30_OKX
pip install -r requirements.txt
cp .env.example .env        # add OKX keys; keep OKX_DEMO=1 to start
```

Create OKX API keys with **Trade** permission. For paper testing use the OKX
**Demo Trading** keys and keep `OKX_DEMO=1`.

---

## Usage

**Backtest** (reproduces the indicator's stats on real OKX history):
```bash
python -m bot.main backtest --bars 1500 --months 8 --verbose
```

**Dry-run** (default — polls live 30m closes, logs intended trades, places *no*
orders):
```bash
python -m bot.main run            # BOT_MODE=dry-run
```

**Live** (places real OKX orders — demo or real per `OKX_DEMO`):
```bash
BOT_MODE=live python -m bot.main run
```

**Inspect resolved config** (secrets redacted):
```bash
python -m bot.main config
```

Configure everything in `config.yaml`; secrets and `BOT_MODE` / `OKX_DEMO` come
from the environment and always override the file.

---

## How live execution maps to OKX

- When a plan is ready to rest on the exchange (pullback break confirmed, or a
  mid-level order active), the bot places a **limit** entry with an **attached
  OCO TP/SL** (`attachAlgoOrds`), so OKX enforces the exit even if the bot is
  offline.
- Orders are keyed by a stable signature so a restart never double-places, and
  the executor's state is persisted to `state/bot_state.json`.
- Plan expiry and mid-cancel cancel the resting limit order if it hasn't filled.
- Contract size is read from the live instrument spec (`ctVal`/`lotSz`/`minSz`);
  leverage and margin mode come from `sizing`.

**Operational notes**

- The bot acts on **closed** 30m bars, matching the indicator (which evaluates on
  bar close). Between bars, resting orders and OKX-side TP/SL remain active.
- Run it under a supervisor (`systemd`, `pm2`, `docker restart=always`) so it
  survives crashes; state is restored from disk on restart.
- Ensure your OKX position mode (net vs. hedge) matches `exchange.hedge_mode`.

---

## Tests

```bash
python -m pytest tests/ -q
```

Covers pivots/ATR, the exact Pine trade-level math for every SL/TP mode,
risk-based sizing, pattern detection, win/loss resolution (including the
pessimistic ambiguous-bar rule), and the trade-day filter.
