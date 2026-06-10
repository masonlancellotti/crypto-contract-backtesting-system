# NEXT_STEPS.md

> Updated 2026-06-10. State: `PROJECT_STATE.md`. Evidence: `RESEARCH_LEDGER.md`.

The data pipeline is healthy and the research framework answers questions fast.
What's missing is an edge, and the ledger shows where the remaining candidates
live. The next steps are mostly *decisions and inputs*, not code:

## 1. ~~Kalshi API key~~ DONE (2026-06-10)
Credentials were already configured in `.env`. `kalshi-ws-feasibility` verified
the read-only market-data WebSocket: connected + subscribed, ~410 book
updates/s, median receive age 14ms. `KALSHI_HIRES_BOOK_SOURCE=auto` is set, so
the hi-res recorder uses WS book deltas (REST fallback). Keep the loop running:
```powershell
python -m btc5m.cli kalshi-hires-record-loop --series KXBTC15M --session-seconds 900
python -m btc5m.cli kalshi-hires-status     # check accumulation
```

## 2. ~~Trade-print collection~~ DONE (2026-06-10)
`kalshi-collect-continuous` now records public trade prints (`kalshi_trades`
stream, taker_side included) every ~5s alongside books.

## 2b. Re-run the blocked studies once WS + trade-print data accumulates
After a few hundred windows of sub-second book data and trade prints
(~2-4 days of the two loops running):
- maker-entry v2 with REAL fills (join prints to resting-quote hypotheses)
- reprice-lag v3 on WS-resolution joins (the +250/500ms horizons that were
  0%-covered under REST polling)

## 3. Verify the deep-favorite YES cell on forward data (patience, no code)
Two independent studies show YES at 90c+ earning ~+1–2c (market underprices
YES by ~1.2c overall). Re-run after a few hundred new windows:
```powershell
python -m btc5m.cli kalshi-maker-entry-study --series KXBTC15M
python -m btc5m.cli kalshi-calibrator-replacement-review --series KXBTC15M
```
If the cell survives on data collected AFTER 2026-06-10, it is the first
candidate worth a shadow experiment (`kalshi-paper-experiment-start
--experiment-mode shadow`) with the freshly promoted pair.

## 4. Keep the collector running
```powershell
.\scripts\collect_kalshi_continuous.ps1
```
Every concluded-negative verdict gets stronger, and every future test gets
cheaper, with more windows.

## 5. Optional strategic forks (bigger decisions)
- **Cross-venue:** fund the Polymarket account → revive the 5m leg from git
  history → measure Kalshi-vs-Polymarket BTC price gaps.
- **Other Kalshi series:** the entire pipeline is series-parameterized;
  hourly/daily BTC (or non-BTC) series may be less efficiently priced than the
  15m sprint market. A discovery scan of spreads/volumes across series is a
  cheap first look.

## What NOT to do next
Don't train more models on the same REST-cadence data, don't tune
buffers/thresholds to force trades, and don't enable paper/live off the
current evidence. The ledger documents why each of those is a dead end.
