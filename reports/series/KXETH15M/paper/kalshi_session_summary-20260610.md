# Kalshi BTC 15m — paper session summary (20260610)

- run_duration_s: None
- markets_discovered: 1034
- open/current: 1  upcoming: 33  closed: 0  settled: 1000
- raw_orderbook_rows: 154
- normalized_orderbook_rows: 154
- underlying_events: 924
- labels_backfilled: 3
- feature_rows_built: 154

## Decisions by state
- NO_ACTION: 48
- WATCH: 12
- MANUAL_REVIEW: 9
- PAPER_CANDIDATE: 0
- REJECTED: 7

- paper_candidates: 0
- simulated_fills: 0
- rejections: 7

## Fee assumptions
- fee_status: ASSUMED  rate: 0.07
- formula: round_up_cent(rate * contracts * price * (1 - price))

## Blockers
- authoritative gate_windows=3 < 60

## Safety
- live trading disabled by default; record-only; no orders placed.

## Next 3 actions
1. Keep the collector running across many 15m windows.
2. Watch kalshi-data-readiness feature_backed_official_windows toward 60/150.
3. When backtest_allowed, fit + calibrate before trusting any PAPER_CANDIDATE.
