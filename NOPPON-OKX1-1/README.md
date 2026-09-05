# NOPPON-OKX1-1 — Session Breakout BTC Perp OKX Bot (30m)

A Python trading bot for **BTC-USDT-SWAP on OKX (30-minute)** that faithfully
ports the `NOPPON-GOLD1-1` TradingView Pine Script indicator (Session Range
Breakout strategy).

> **Trading risk.** This software can place real orders and lose real money.
> It defaults to **dry-run** (no orders) and **OKX demo** trading. Test on demo
> thoroughly before risking funds. No warranty of any kind.

---

## Strategy

1. **Session Range** — Track forex session windows (Sydney/Tokyo/London/NewYork)
   with DST awareness (Apr-Sep). Build range from session high/low.
2. **OCO Plans** — On session end, create Buy Stop (at session high) + Sell Stop
   (at session low) pair. When one fills, the other is cancelled.
3. **Entry Modes**:
   - **Breakout** — enter when price breaks session edge
   - **Pullback** — break edge, wait for X% pullback into range, then fill
   - **PB+Re-break** — break, pullback, then re-break the edge
4. **2nd Order** — When main hits SL, arm a re-break entry at the same level
5. **50% Add-on** — When main is open and price pulls back to 50% of session
   range, open an add-on order
6. **Trailing SL** — Trigger at X R, lock at Y R
7. **Close on New Session** — Close open main orders when next session starts
8. **Risk** — 1R from SL% / Fixed Distance / ATR; TP from R:R ratio

---

## Layout

```
bot/
  config.py     # all strategy params (mirrors Pine inputs) + YAML/env loading
  indicators.py # Wilder ATR
  engine.py     # pure bar-for-bar strategy engine (backtest + live share it)
  okx_client.py # OKX v5 REST client (market data + signed trading)
  data.py       # candle fetch/parse/pagination
  executor.py   # engine events -> real OKX limit + attached TP/SL
  runner.py     # warmup + dry-run/live loop
  stats.py      # overall / by-day / monthly tables
  backtest.py   # historical backtest
  main.py       # CLI
tests/          # unit tests
config.yaml     # editable defaults
```

---

## Setup

```bash
cd NOPPON-OKX1-1
pip install -r requirements.txt
cp .env.example .env        # add OKX keys; keep OKX_DEMO=1 to start
```

---

## Usage

**Backtest:**
```bash
python -m bot.main backtest --bars 1500 --months 8 --verbose
```

**Dry-run** (default — logs intended trades, places no orders):
```bash
python -m bot.main run
```

**Live** (places real OKX orders):
```bash
BOT_MODE=live python -m bot.main run
```

**Inspect config:**
```bash
python -m bot.main config
```

---

## Tests

```bash
python -m pytest tests/ -q
```
