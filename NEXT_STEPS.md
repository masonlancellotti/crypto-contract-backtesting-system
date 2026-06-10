# NEXT_STEPS.md

> Updated 2026-06-10. State: `PROJECT_STATE.md`. Evidence: `RESEARCH_LEDGER.md`.

The data pipeline is healthy and the research framework answers questions fast.
What's missing is an edge, and the ledger shows where the remaining candidates
live. The next steps are mostly *decisions and inputs*, not code:

## 1. Generate a Kalshi API key (user action; free; unlocks the most)
Kalshi gates even read-only market-data WebSocket behind an account API key
(RSA). With it:
```powershell
# verify the key works, read-only (no orders, no account writes):
python -m btc5m.cli kalshi-ws-feasibility --series KXBTC15M
# then run the hi-res recorder on WS book deltas instead of ~1.1s REST polls:
#   KALSHI_HIRES_BOOK_SOURCE=websocket
python -m btc5m.cli kalshi-hires-record --series KXBTC15M
```
This is the only way to resolve the three OPEN legs (maker entries, both-sides
quoting, sub-second stale-quote) — REST snapshots at 1–4s provably cannot.
Set `KALSHI_KEY_ID` + `KALSHI_PRIVATE_KEY_PATH` in `.env` (never in chat).

## 2. Add public trade-print collection (small code task, no auth)
Kalshi exposes recent trades via public REST. Recording them alongside books
would tighten the maker-entry fill model (real fills instead of trade-through
lower bounds). Worth doing even before the API key exists.

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
