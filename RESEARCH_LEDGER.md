# RESEARCH_LEDGER.md — every hypothesis, its result, and its status

> One line of truth per research leg. Before starting new work, check whether the
> idea is already here. Every entry links to the module/command that reproduces it.
> Updated 2026-06-10.

## How to read this
- **CONCLUDED-NEGATIVE** = tested honestly, no edge after costs at the data
  resolution we have. Don't re-run it on more of the same data expecting a
  different answer; re-open only if the *inputs* change (better data, fees, venue).
- **OPEN** = promising or unresolved; the blocking input is named.
- **INFRA** = measurement/safety capability, not an edge claim.

## The one-paragraph summary
KXBTC15M is a tight, well-calibrated market: median spread ~1c, taker fee ~1.5c,
market-implied probability is the best-calibrated forecaster we have measured
(distinct-window ECE ≈ 0.02, vs 0.03+ for every model we trained). Every taker
strategy tested — direct model, recalibrated model, residual-over-market models,
stale-quote sniping — fails to clear the ~2.5c round cost out-of-sample. The
conservative lower bound on maker (passive) entries is also negative, but that
bound is provably pessimistic and can only be tightened with trade prints and
sub-second WebSocket book data — both of which are RECORDING as of 2026-06-10
(API credentials were already configured in `.env`; the WS delivers ~410 book
updates/s at 14ms median receive age). Those studies, or a structural change
(cross-venue, different series), are where remaining edge could live. The
system itself is healthy: it measures honestly and fails fast.

## Ledger

| # | Hypothesis / leg | Where | Result | Status |
|---|---|---|---|---|
| 1 | Polymarket BTC 5m Up/Down pipeline (original project) | git history (removed 2026-06-10); venue semantics in `docs/archive/` | Full record/label/feature pipeline worked; discovery bug found+fixed; venue parked for account/funding reasons before model evidence | PARKED (code removed; restorable from git) |
| 2 | Kalshi KXBTC15M collection + OFFICIAL labeling | `kalshi-collect-continuous`, `kalshi-data-readiness` | 770 usable gate windows, ~240k book snapshots, ~700k underlying rows; both train (150) and backtest (60) gates passed | INFRA — keep running |
| 3 | A model on book+microstructure features beats the Kalshi price (taker) | `kalshi-train-baselines`, `kalshi-backtest-baselines` | AUC 0.90 but market-implied is better calibrated (window-ECE 0.020 vs 0.031+); fitted baselines LOSE after fees at the ask; market-implied trades 0 by construction | CONCLUDED-NEGATIVE |
| 4 | Isotonic calibration makes the model tradable | `kalshi-calibration-report`, memory: calibration-buffer audit | June-3 isotonic OVERFIT (test ECE 0.040→0.076), created a real bias-dominated 5–16c edge buffer; fixed 2026-06-10 by retrain+repromote on 770 windows (ECE 0.058→0.026, overfit_risk low) | RESOLVED (hygiene, not edge) |
| 5 | Confidence-aware edge policy (Wilson buffers, reservation prices) | `kalshi-edge-policy-report`, `kalshi-uncertainty-audit` | Buffers are mathematically correct and bias-dominated; policy correctly blocks ~all candidates (1/137 positive final edge in shadow) | INFRA — working as designed |
| 6 | Shadow "passes" indicate edge | `shadow_compare` ledgers 06-06→06-08 | Pass rows = regime luck: wins track realized window direction; fades 0/5; "identity knife-catches down windows" (14% win) | CONCLUDED-NEGATIVE |
| 7 | Trade more / trade less (frequency frontier) | `kalshi-frequency-report` + sweeps | Marginal trades stop adding value almost immediately; distinct windows matter more than trade count; overtrading destroys | INFRA — informs caps |
| 8 | Kalshi quotes lag BTC moves (stale-quote, v1 at ~4s data) | `kalshi-reprice-lag-study` | NULL: detected "opportunities" lose; median lag 0c; 4s cadence cannot even see the hypothesis | CONCLUDED-NEGATIVE at this resolution |
| 9 | Sub-second measurement layer | `kalshi-hires-record`, `hires/` | Works: Binance ~27ms, Coinbase ~120ms ticks; Kalshi REST book ~1.1s (RTT-bound) | INFRA |
| 10 | Stale-quote v2 on hi-res joins | `kalshi-reprice-lag-study --hires` | NEGATIVE: win 0%, no fee-surviving edge; +250/500ms response horizons ~0% covered because the Kalshi book is REST-polled at ~1.1s | UNBLOCKED 2026-06-10: WS book source live (~410 upd/s); re-run after hi-res WS data accumulates |
| 11 | Residual-over-market models (predict y − p_market) | `kalshi-train-residual-models` | No model stably beats market OOS (walk-forward deltas flip sign; ICs flip sign); lightgbm's +2.14 single-split backtest has the WORST calibration (ECE 0.070) = luck | CONCLUDED-NEGATIVE |
| 12 | Replace the overfit calibrator with a safer one | `kalshi-calibrator-replacement-review`, `kalshi-paper-calibrator-swap-review` | Fresh isotonic ≈ break-even (+0.73 over 179 test windows); market-implied best calibrated (0.0199) but is the price (no edge); swap gate declined all candidates; superseded by full re-promotion 2026-06-10 | RESOLVED |
| 13 | Maker (passive) entries recover the spread+fee | `kalshi-maker-entry-study` (2026-06-10) | Spread is only ~1c median; conservative trade-through lower bound NEGATIVE (YES −3.6c, NO −2.1c per fill — adverse selection > savings); `win\|no-fill ≈ 100%` confirms selection; bound is provably pessimistic (fills undercounted, worst subset counted) | OPEN — trade prints + WS book both recording since 2026-06-10; re-run when a few hundred windows exist |
| 14 | Both-sides quoting (one-shot, join-bid both legs) | same study | 71.2% double-fill rate, +0.96c locked per pair, ≈ −0.1c/quote net after naked single-fill legs at the lower bound | OPEN — same as 13; inputs now recording |
| 15 | Deep-favorite YES bias (market underprices YES overall by ~1.2c; YES at 90c+ shows maker +2.05c, taker +0.96c over 262 windows) | maker study by-price table; calibrator review (`market_implied YES_overpred −1.16c`) | Only consistently positive cell across studies; small, plausibly real (favorite-longshot-like), but one cell among many (multiple-comparisons risk) | OPEN — verify on forward data before sizing |
| 16 | Kalshi market-data WebSocket feasibility | `kalshi-ws-feasibility` | VERIFIED 2026-06-10 with configured creds: connected+subscribed, ~410 book updates/s, median recv age 14ms, sub-second available; `KALSHI_HIRES_BOOK_SOURCE=auto` now active (WS preferred, REST fallback) | RESOLVED — WS in use |
| 17 | Deribit vol/options as model features | `record-deribit`, `DERIBIT_*` flags | Joined point-in-time as optional features; no standalone edge shown; ablation delta-Brier ≈ −0.0001 | INFRA — optional, off by default |

## What is NOT worth doing (without new inputs)
- Re-training bigger/fancier models on the same ~1–4s REST data. Three model
  families and a residual reformulation all converge to "the price is better."
- Re-running shadow experiments hoping passes accumulate (leg 6 explains why).
- Threshold/buffer tuning to "let trades through" — the buffers are measuring
  real bias, not being conservative for fun.

## What unlocks new information (in value order)
1. ~~Kalshi API key~~ **DONE 2026-06-10** — creds were already in `.env`; WS
   verified (~410 upd/s, 14ms) and the hi-res recorder now uses it
   (`KALSHI_HIRES_BOOK_SOURCE=auto`). Legs 10/13/14 need accumulated WS data,
   then re-run their studies.
2. ~~Public trade prints~~ **DONE 2026-06-10** — the collector records
   `kalshi_trades` rows (taker_side included) every ~5s.
3. **Forward verification of leg 15** (deep-favorite YES) on data collected
   after 2026-06-10 — zero new infrastructure needed, just patience.
4. **Cross-venue (Polymarket BTC) price comparison** — needs the parked account
   funded; the 5m pipeline is in git history if revived.
