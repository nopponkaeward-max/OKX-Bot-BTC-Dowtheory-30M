# Strategy Research Log — BTC-USDT-SWAP (OKX real data)

Brief: find NEW entries (different from the DowTheoryBreak bot), RR 1:1,
SL/TP distance >= 500 pts, target winrate >= 70%. Resolution is pessimistic
(both TP & SL touched in one bar = loss), so winrates are conservative floors.
Entries are market orders at the next bar open after the signal; one position
at a time; no fees included.

Data: 15m (Mar–Sep 2026), 30m (Dec 2025–Sep 2026), 1H/2H (Aug 2025–Sep 2026),
4H (Jul 2025–Sep 2026). Cached in `research/data/`.

---

## Round 1 (2026-09-03) — broad grid, 34 strategies x 5 TF x 5 distances

Families: RSI reversal/cross-back, Bollinger reversion, consecutive-close
reversal, big-candle fade, EMA cross, stochastic reversal, funding-hour,
pin-bar. **No candidate reached 70%.** Best ~66% (stoch14 10/90, 30m d1500,
315 trades, +101R). Clear cluster: 30m mean-reversion @ dist 1500–2000 all
land 62–66% with positive netR.

## Round 2 (2026-09-03) — filters, confluence, larger distances

Winner: **`confl_stoch+fade`** = Stochastic %K(14) extreme (<10 long / >90
short) AND bar range > 2.5x ATR(14) closing in the stretch direction → fade
(enter against the big bar at next open).

| TF  | dist | trades | win%  | netR | 1st half | 2nd half | LONG | SHORT |
|-----|------|--------|-------|------|----------|----------|------|-------|
| 30m | 1500 | 81     | 76.5% | +43  | 92.5%    | 61.0%    | 73%  | 80%   |
| 30m | 2000 | 76     | 76.3% | +40  | 86.8%    | 65.8%    | 76%  | 76%   |
| 30m | 2500 | 64     | 79.7% | +38  | 87.5%    | 71.9%    | 79%  | 81%   |
| 30m | 3000 | 55     | 80.0% | +33  | 81.5%    | **78.6%**| 78%  | 82%   |
| 1H  | 1500 | 51     | 74.5% | +25  | 84.0%    | 65.4%    | 74%  | 75%   |
| 1H  | 2000 | 50     | 76.0% | +26  | 88.0%    | 64.0%    | 73%  | 79%   |

Robustness notes:
* Both sides profitable, works on two TFs and across all distances — not a
  single lucky parameter cell.
* Time decay exists: Dec-25→Mar-26 was exceptional; Apr-26 was the worst
  month (1–2 wins of 5–6). **dist 3000 on 30m is the most stable**
  (81.5% → 78.6% across halves).
* Avg hold at 30m d3000 ≈ 115 bars (~2.4 days); d1500 ≈ 24 bars (~12 h).
* Caveats: ~9 months of data, 55–81 trades, no fees (at d2000+, round-trip
  taker fees ≈ 0.1% of notional vs a ≥2% target → ~5% of R).

### Current leaderboard (>= 70% & >= 30 trades)
1. confl_stoch+fade 30m d3000 — 80.0% / 55 trades / +33R  ← most stable
2. confl_stoch+fade 30m d2500 — 79.7% / 64 trades / +38R
3. confl_stoch+fade 30m d1500 — 76.5% / 81 trades / +43R
4. confl_stoch+fade 30m d2000 — 76.3% / 76 trades / +40R
5. confl_stoch+fade 1H  d2000 — 76.0% / 50 trades / +26R
6. confl_stoch+fade 1H  d1500 — 74.5% / 51 trades / +25R

Near-misses worth revisiting: range50_edge_rev 30m d2000 (69.4%/121t),
confl_stoch+boll 30m d2000 (69.0%/168t, more trades), fade2.5_wtrend 2H
d2000 (69.7%/33t).

## Next (round 3 plan)
* Volatility-regime & session filters on the near-misses.
* Keltner touch, Donchian-mid reversion, liquidation-wick reversal,
  multi-TF confluence (30m signal + 4H trend).
* Re-resolve ambiguous bars of top candidates with real 1m data.
* Longer 30m history (back to 2025) to test confl_stoch+fade out-of-sample.
