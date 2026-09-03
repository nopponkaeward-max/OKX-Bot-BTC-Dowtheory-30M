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

## Round 3 (2026-09-03) — OOS test, plateau map, sessions, new families

30m data extended to 15 months (Jun 2025 – Sep 2026, 22000 bars).

**A) Out-of-sample (Jun–Dec 2025, data the strategy never saw): PASSED.**
d1500 83.9% (56t), d2000 77.4%, d2500 72.5%; only d3000 dipped (65.3%).
Full 15-month window: d1500 **79.6% / 137 trades / +81R**, d2000 76.9%/+70R,
d2500 76.7%/+62R, d3000 73.3%/+49R.

**B) Parameter plateau (d2500, 15 months): smooth, no isolated spike.**
Tightening both filters raises winrate monotonically:
stoch<5/>95 + atr>3.0x → **84.9% / 53 trades / +37R**;
loosening to 20/80 + 2.0x still 66.7% / 240 trades / +80R.

**C) Session split: edge exists in all three 8h sessions** (US strongest —
83.0% d1500). New family Keltner(EMA20±3*ATR) reversion also clears 70%
(71.2% / 104t / +44R at d2000).

**Monthly stability (15 months):**
* flagship (10/90, 2.5x, d1500): 12/15 months positive, worst -2R (Apr-26)
* tight (5/95, 3.0x, d2500): 13/15 months positive, worst -2R

### FLAGSHIP CANDIDATE — "Exhaustion Fade"
Entry (all must hold on a closed 30m bar):
1. bar range > 2.5 x ATR(14)  — a climax bar
2. Stoch %K(14) < 10 with a red bar -> LONG next open;
   %K > 90 with a green bar -> SHORT next open
3. TP = SL = 1500 pts (RR 1:1), market entry at next bar open
Result: 79.6% winrate, 137 trades / 15 months (~9/month), +81R,
OOS-confirmed, both sides & all sessions profitable.
Conservative resolution (same-bar double-touch counted as LOSS).
Fees not modeled (~0.1% notional round trip ≈ 7% of one R at d1500).

## Round 4 (2026-09-03) — 1m recheck, filters, new families, TF ports

**A) 1m intrabar recheck: the pessimistic numbers are essentially exact.**
Flagship d1500 had 1 ambiguous bar in 137 trades (flips to a win with real
1m data → 80.3% upper bound vs 79.6% floor). At d1000, 6 of 7 ambiguous
bars really were SL-first — the pessimistic rule is the right default.

**B) Filters (both help slightly, none is required):**
* +Keltner(EMA20±3ATR) confluence: 81.8% / 55t / +35R (d1500)
* high-vol regime only: 80.3% / 61t; low-vol only: 78.5% / 79t
  → the edge exists in BOTH volatility regimes (robustness, not a fix).

**C) New families — dead ends (documented to avoid re-testing):**
gap-fill (too few signals), round-number bounce (45-47%, negative netR),
multi-TF stoch alignment (max 64.3%). None reaches 70%.

**D) Flagship across TFs (same rule, ATR-proportional distances):**
| TF | best | verdict |
|----|------|---------|
| 15m | 54% @ d500-750 | **fails** — climax-fade edge vanishes at 15m |
| 30m | 79.6% @ d1500 (137t) | champion |
| 1H  | 76.0% @ d2000 (50t) | passes |
| 2H  | 80.0% @ d3000 (20t) | passes but thin sample |

## Round 5 (2026-09-03) — execution variant, portfolio stats, more families

**A) Limit-entry variant is WORSE — market entry is the right execution.**
Waiting for a retrace into the climax bar (limit at close ± 25-60% of the
bar range, 16-bar expiry) drops winrate to 58-66% and forfeits most trades:
the best reversals run immediately and never retrace. Dead end; keep
market-at-next-open.

**B) Flagship portfolio quality (30m d1500, 137 trades / 15 months):**
* final equity **+81R**, max drawdown **5R**, max consecutive losses **4**
* every weekday >= 72% winrate (Tue 88%, Sun 72%) — no day filter needed.

**C) 30m + 1H portfolio: 82% of 1H trades overlap an open 30m trade.**
The 1H port is mostly the same exposure, not diversification. Run 30m only
(or accept correlated size-doubling).

**D) New families — all fail (documented dead ends):** failed-breakout
fade (<53%), squeeze-expansion (<61%), first-hour-range follow/fade (<54%).

## Round 6 (2026-09-03) — funding rate, candle patterns, Monday effect

**A) Funding-rate strategies: inconclusive — OKX only serves ~3 months of
funding history** (277 records, Jun–Sep 2026). Funding-extreme fade at low
thresholds is mildly positive (59% / 22-27 trades) but the sample is too
small and sits entirely inside the flagship's weakest season. Parked until
more history accrues.

**B) Funding filter on the flagship: unusable** — only 13 flagship trades
fall inside the 3-month funding window.
⚠ Honest note the window exposes: the flagship's LAST 3 MONTHS
(Jun–Aug 2026) ran 6/13 ≈ 46% — well below the 15-month average of 79.6%.
Small sample (13 trades), but recent regime softness is real and was
already visible in the monthly table (Apr -2R, Jul -1R, Aug -2R).

**C) Candle patterns & Monday-fade-weekend: all fail** (best 61%,
engulfing-after-streak negative). Dead ends documented.

---

## PRODUCTION SPEC — "Exhaustion Fade" v1 (ready to implement on request)

Instrument: BTC-USDT-SWAP · TF: 30m (closed bars only) · direction: both
1. **Signal** on closed bar i:
   * (high−low) > 2.5 × ATR(14)  — ATR uses Wilder smoothing
   * LONG  if Stoch %K(14) < 10 and close < open
   * SHORT if Stoch %K(14) > 90 and close > open
2. **Entry**: market order at the open of bar i+1 (no limit, no retrace —
   round 5 proved waiting loses the edge). One position at a time.
3. **Exit**: attached TP & SL at entry ± 1500 pts (RR 1:1). No trailing,
   no time stop.
4. **Size**: contracts = (risk_usdt / 1500) / ctVal, floored to lot step.
5. Expectations from 15 months of data: ~9 trades/month, 79.6% winrate,
   +81R, max DD 5R, max 4 straight losses; weakest recent quarter ≈ 46%
   over 13 trades — size for a 10R drawdown to be safe.
6. Alternative profile (fewer, better trades): %K <5/>95 + 3.0×ATR,
   dist 2500 → 84.9%, ~3.5 trades/month.

## Round 7 (2026-09-03) — DEEP OOS on 2.7 years: the edge is REGIME-DRIVEN

30m data extended to Dec 2023 – Sep 2026 (47,000 bars).

**A) Flagship by calendar year (fixed d1500):**
| year | trades | win% | netR |
|------|--------|------|------|
| 2024 | 65 | **55.4%** | +7 |
| 2025 | 99 | **84.8%** | +69 |
| 2026 | 67 | **71.6%** | +29 |
| ALL (2.7y) | 231 | **72.7%** | **+105** |

Price-proportional distances (1.0–2.0% of price, floor 500) tell the same
story — the yearly split is a regime property, not a distance artefact.

**B) Rolling 50-trade winrate:** flat ~56% through 2024→mid-2025, ignites
to 84–88% around Dec-2025→Feb-2026, and has cooled to ~60% by Aug-2026.

**Honest verdict:** Exhaustion Fade is profitable over the whole 2.7 years
(+105R, 72.7% — still above the 70% brief overall) and never had a losing
year, but the spectacular 79.6% figure came from a hot regime that is
currently cooling. Live expectation today should be ~60-70%, not 80%. A
regime monitor (e.g., stand aside if the rolling 20-trade winrate < 55%)
belongs in any production deployment.

**C) New families — all fail again:** two-bar reversal (46%, heavily
negative), volume-climax wick (<52%), Keltner re-entry (<53%).

## Next (round 8 plan)
* Re-run ALL prior >=65% families over the full 2.7 years — which survive
  2024+2025+2026 with every year >= 60%? (new, stricter bar)
* Walk-forward regime gate on the flagship: trade only while the rolling
  20-signal winrate >= 55%; measure live-like performance.
* Probe what switched on in mid-2025 (ATR%/price level? trend regime?)
  to build a forward-looking gate instead of a backward-looking one.
