# Forward Test Log — Exhaustion Fade TIGHT (30m)

Live-data tracking of the validated strategy (research/RESULTS.md final
report) using real OKX BTC-USDT-SWAP 30m candles, checked periodically.
Rule: %K(14) <5 (red bar → LONG) / >95 (green bar → SHORT), bar range >
3.0×ATR(14), market entry at next open, TP=SL=max(2.3% of entry, 500 pts).

Log format per check: UTC timestamp of check, new signals found (if any),
resolutions of previously-open trades (if any), running W/L tally.

---

## Check #1 — 2026-09-04 08:2x UTC

- Data: last 299 confirmed 30m bars (2026-08-29 → 2026-09-04), OKX API.
- Open trades to resolve: none (first check).
- New signals: **none** in this window.
- Running tally: 0W / 0L (0 trades since forward-test start).

Note: at ~3 signals/month for TIGHT, a 6-day window with zero signals is
normal, not a red flag. Next check in ~6h will extend the lookback via
the historical cache rather than only the last 299 bars.

## Check #2 — 2026-09-04 14:2x UTC

- Data: last 299 confirmed 30m bars (2026-08-29 → 2026-09-04), OKX API.
- Price moved 81,718 → 79,347 (~-2.9%) over this 6h gap; no bar met the
  3.0×ATR climax + %K<5/>95 condition, so no signal despite the move.
- Open trades to resolve: none.
- New signals: **none**.
- Running tally: 0W / 0L (0 trades since forward-test start).

## Check #3 — 2026-09-04 20:2x UTC

- Data: last 299 confirmed 30m bars (2026-08-29 → 2026-09-04), OKX API.
- Price ~79,772 (roughly flat vs check #2's 79,347).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L.

## Check #4 — 2026-09-05 02:3x UTC

- Data: last 299 confirmed 30m bars (2026-08-29 → 2026-09-05), OKX API.
- Price ~79,485 (flat vs check #3's 79,772).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. No TIGHT signal in 6+ days now — within normal
  range for a ~3/month strategy, but the next check will flag if this
  extends much further.

## Check #5 — 2026-09-05 08:3x UTC

- Data: last 299 confirmed 30m bars (2026-08-30 → 2026-09-05), OKX API.
- Price ~80,436 (up slightly from check #4's 79,485).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell now ~7 days — still inside normal
  variance (expected gap between ~3 signals/month is ~10 days on average).

## Check #6 — 2026-09-05 14:3x UTC

- Data: last 299 confirmed 30m bars (2026-08-30 → 2026-09-05), OKX API.
- Price ~79,687 (down slightly from check #5's 80,436).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~8 days.

## Check #7 — 2026-09-05 20:3x UTC

- Data: last 299 confirmed 30m bars (2026-08-30 → 2026-09-05), OKX API.
- Price ~79,682 (flat vs check #6's 79,687).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~9 days — approaching the ~10-day
  average gap for a 3-signal/month strategy. If no signal by check #10,
  will note but not intervene (strategy parameters are locked).

## Check #8 — 2026-09-06 02:4x UTC

- Data: last 299 confirmed 30m bars (2026-08-30 → 2026-09-06), OKX API.
- Price ~79,875 (up from check #7's 79,682).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~10 days — now at the expected average
  gap between signals for a ~3/month strategy. No cause for concern yet.

## Check #9 — 2026-09-06 08:4x UTC

- Data: last 299 confirmed 30m bars (2026-08-31 → 2026-09-06), OKX API.
- Price ~79,764 (flat vs check #8's 79,875).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~10 days — still within normal range.

## Check #10 — 2026-09-06 14:4x UTC

- Data: last 299 confirmed 30m bars (2026-08-31 → 2026-09-06), OKX API.
- Price ~79,633 (down slightly from check #9's 79,764).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~11 days — still within normal
  variance for a ~3 signals/month strategy (expected average gap ~10 days;
  longer gaps are common).

## Check #11 — 2026-09-06 21:0x UTC

- Data: last 299 confirmed 30m bars (2026-08-31 → 2026-09-06), OKX API.
- Price ~79,876 (up from check #10's 79,633).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~12 days — still within normal
  variance; BTC ranging 79k-80k with low volatility, which suppresses
  the 3×ATR climax condition.

## Check #12 — 2026-09-07 03:1x UTC

- Data: last 299 confirmed 30m bars (2026-09-01 → 2026-09-07), OKX API.
- Price ~79,840 (flat vs check #11's 79,876).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~12 days — BTC continues ranging
  79k-80k; no 3×ATR climax bars in this low-volatility environment.

## Check #13 — 2026-09-07 09:1x UTC

- Data: last 299 confirmed 30m bars (2026-09-01 → 2026-09-07), OKX API.
- Price ~79,396 (down from check #12's 79,840).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~13 days — price dipped toward 79k
  but still no single bar met the 3×ATR climax threshold.

## Check #14 — 2026-09-07 15:1x UTC

- Data: last 299 confirmed 30m bars (2026-09-01 → 2026-09-07), OKX API.
- Price ~79,156 (down from check #13's 79,396).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~13 days — BTC drifting lower in a
  tight 79k-80k range; volatility remains too low to produce 3×ATR climax
  bars. Strategy parameters are locked; no intervention warranted.

## Check #15 — 2026-09-07 21:3x UTC

- Data: last 299 confirmed 30m bars (2026-09-01 → 2026-09-07), OKX API.
- Price ~79,194 (up slightly from check #14's 79,156).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~14 days — BTC still ranging 79k-80k;
  no bar met the 3×ATR climax threshold. Expected for a ~3 signals/month
  strategy during low-volatility consolidation.

## Check #16 — 2026-09-08 03:4x UTC

- Data: last 290 confirmed 30m bars (2026-09-01 → 2026-09-08), OKX API.
- Price ~78,736 (down from check #15's 79,194; BTC broke below 79k).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~14 days — despite the selloff from
  ~79.2k to ~78.7k, no single 30m bar met the 3×ATR climax + %K threshold.
  The move was spread across multiple bars rather than one climax candle.

## Check #17 — 2026-09-08 09:3x UTC

- Data: last 299 confirmed 30m bars (2026-09-02 → 2026-09-08), OKX API.
- Price ~78,437 (down from check #16's 78,736; BTC continuing to slide).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~15 days — BTC drifting lower through
  78k-79k; moves remain gradual across multiple bars rather than producing
  single 3×ATR climax candles. No intervention warranted; strategy
  parameters are locked.

## Check #18 — 2026-09-08 16:1x UTC

- Data: last 299 confirmed 30m bars (2026-09-02 → 2026-09-08), OKX API.
- Price ~78,866 (up from check #17's 78,437; BTC bounced off 77k support).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~15 days — despite a drop to ~76.2k
  and recovery to ~78.9k, moves continue to spread across multiple bars
  rather than producing single 3×ATR climax candles. Strategy parameters
  are locked; no intervention warranted.

## Check #19 — 2026-09-08 22:2x UTC

- Data: last 274 confirmed 30m bars (2026-09-03 → 2026-09-08), OKX API.
- Price ~78,460 (down from check #18's 78,866; gave back earlier bounce).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~16 days — BTC oscillating in 78k-79k
  range with no single bar meeting the 3×ATR climax threshold. Strategy
  parameters are locked.

## Check #20 — 2026-09-09 04:2x UTC

- Data: last 299 confirmed 30m bars (2026-09-02 → 2026-09-09), OKX API.
- Price ~78,594 (up from check #19's 78,460; slight recovery).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~17 days — BTC oscillating in 78k-79k
  range; a brief dip to ~76.2k and recovery occurred during this window but
  moves remain spread across multiple bars rather than single 3×ATR climax
  candles. Strategy parameters are locked.

## Check #21 — 2026-09-09 10:3x UTC

- Data: last 209 confirmed 30m bars (2026-09-05 → 2026-09-09), OKX API.
- Price ~79,052 (up from check #20's 78,594; BTC recovered above 79k).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~17 days — BTC bounced from ~78.4k
  to ~79k but moves remain gradual across multiple bars. No single bar
  met the 3×ATR climax + %K threshold. Strategy parameters are locked.

## Check #22 — 2026-09-09 16:5x UTC

- Data: last 299 confirmed 30m bars (2026-09-03 → 2026-09-09), OKX API.
- Price ~78,609 (down from check #21's 79,052; BTC sold off through 79k).
- Notable: bar at 15:00 UTC had a 1,348-pt range (79,376→78,028) but the
  scanner confirms it did not meet both 3×ATR and %K<5/%K>95 simultaneously.
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~17 days — BTC trending lower from
  ~81k to ~78.6k over the past few days; large intraday moves are occurring
  but spread across multiple bars or not meeting both filter conditions.
  Strategy parameters are locked.

## Check #23 — 2026-09-09 23:0x UTC

- Data: last 285 confirmed 30m bars (2026-09-04 → 2026-09-09), OKX API.
- Price ~77,887 (down sharply from check #22's 78,609; BTC broke below 78k).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~18 days — BTC continuing to sell off
  from ~81k to ~77.9k over the past few days; moves remain spread across
  multiple bars rather than producing single 3×ATR climax candles. Strategy
  parameters are locked.

## Check #24 — 2026-09-10 05:1x UTC

- Data: last 225 confirmed 30m bars (2026-09-05 → 2026-09-10), OKX API.
- Price ~78,372 (up from check #23's 77,887; BTC recovered above 78k).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~18 days — BTC bounced from ~77.9k
  back to ~78.4k but continues ranging without producing single 3×ATR
  climax candles. Strategy parameters are locked.

## Check #25 — 2026-09-10 11:2x UTC

- Data: last 299 confirmed 30m bars (2026-09-04 → 2026-09-10), OKX API.
- Price ~77,832 (down from check #24's 78,372; BTC slid below 78k again).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~19 days — BTC continuing to drift
  lower through 77k-78k range; no single bar met the 3×ATR climax + %K
  threshold. Strategy parameters are locked.

## Check #26 — 2026-09-10 17:3x UTC

- Data: last 299 confirmed 30m bars (2026-09-04 → 2026-09-10), OKX API.
- Price ~77,300 (down sharply from check #25's 77,832; BTC broke below 77.5k).
- Notable: bar at ~13:30 UTC had a 1,350-pt range (77,957→76,607) but the
  scanner confirms it did not meet both 3×ATR and %K<5/%K>95 simultaneously.
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~19 days — BTC accelerating lower
  from ~78k to ~77.3k; volatility increasing but still not producing
  single bars meeting both filter conditions. Strategy parameters are locked.

## Check #27 — 2026-09-10 23:4x UTC

- Data: last 247 confirmed 30m bars (2026-09-05 → 2026-09-10), OKX API.
- Price ~76,698 (down sharply from check #26's 77,300; BTC broke below 77k).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~19 days — BTC continuing to sell off
  from ~77.3k to ~76.7k; moves remain spread across multiple bars rather
  than producing single 3×ATR climax candles. Strategy parameters are locked.

## Check #28 — 2026-09-11 05:5x UTC

- Data: last 299 confirmed 30m bars (2026-09-05 → 2026-09-11), OKX API.
- Price ~77,061 (up from check #27's 76,698; BTC bounced back above 77k).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~20 days — BTC oscillating in 76k-77k
  range; no single bar met the 3×ATR climax + %K threshold. Strategy
  parameters are locked.

## Check #29 — 2026-09-11 12:0x UTC

- Data: last 291 confirmed 30m bars (2026-09-05 → 2026-09-11), OKX API.
- Price ~77,000 (flat vs check #28's 77,061; BTC holding around 77k).
- Open trades to resolve: none. New signals: **none**.
- Running tally: 0W / 0L. Dry spell ~20 days — BTC consolidating around
  76.8k-77.3k; no single bar met the 3×ATR climax + %K threshold. Strategy
  parameters are locked.

## Check #30 — 2026-09-11 18:1x UTC

- Data: last 299 confirmed 30m bars (2026-09-05 → 2026-09-11), OKX API.
- Price ~77,500 (up from check #29's 77,000; BTC volatile with massive
  intraday swings).
- **FIRST SIGNAL! SHORT at 2026-09-11 13:30 UTC bar:**
  - Signal bar: O=77,484.9 H=79,316.6 L=77,220.0 C=79,202.9
  - Green bar, %K(14)=96.7 (>95), range=2,096.6 > 3×ATR(14)=1,620.0
  - Entry: SHORT at next bar open = 79,203.0 (14:00 UTC bar)
  - TP/SL = max(2.3% × 79,203, 500) = 1,821.7 pts
  - TP = 77,381.3, SL = 81,024.7
  - **TP HIT at 15:30 UTC bar** (low=77,252.1 ≤ 77,381.3) → **WIN**
  - Trade duration: 3 bars (1.5 hours)
- Running tally: **1W / 0L** (100% win rate, +1,821.7 pts). Dry spell
  broken after 20 days — a violent BTC spike from ~77k to ~79.3k in a
  single 30m bar triggered the exhaustion fade, which then reversed
  ~1,950 pts within 2 hours. Textbook climax exhaustion.

## Check #31 — 2026-09-12 00:2x UTC

- Data: last 299 confirmed 30m bars (2026-09-05 → 2026-09-12), OKX API.
- Price ~77,236 (down from check #30's 77,500; BTC drifting lower after
  yesterday's volatility spike).
- Open trades to resolve: none (check #30's SHORT already resolved as WIN).
- New signals: **none** (only the already-resolved 13:30 signal in window).
- Running tally: **1W / 0L** (+1,821.7 pts).

## Check #32 — 2026-09-12 06:3x UTC

- Data: last 299 confirmed 30m bars (2026-09-06 → 2026-09-12), OKX API.
- Price ~77,214 (down from check #31's 77,236; BTC flat around 77k).
- Open trades to resolve: none. New signals: **none**.
- Running tally: **1W / 0L** (+1,821.7 pts).

## Check #33 — 2026-09-12 12:3x UTC

- Data: last 299 confirmed 30m bars (2026-09-06 → 2026-09-12), OKX API.
- Price ~77,290 (flat vs check #32's 77,214; BTC consolidating around 77k).
- Open trades to resolve: none. New signals: **none** (only the
  already-resolved 13:30 signal from check #30 in window).
- Running tally: **1W / 0L** (+1,821.7 pts).
