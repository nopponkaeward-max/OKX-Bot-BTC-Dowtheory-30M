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

## Next (round 5 plan)
* Limit-entry variant (retrace into the climax bar) vs market entry.
* Portfolio stats for flagship: equity curve in R, max drawdown, streaks.
* Day-of-week breakdown; combined 30m+1H portfolio overlap check.
* New families: failed-breakout fade (fakeout), squeeze-expansion,
  first-hour range strategies.
