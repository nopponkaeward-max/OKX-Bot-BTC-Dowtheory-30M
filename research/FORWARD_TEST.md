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
