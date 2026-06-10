# PROJECT_STATE.md

> Read this + `RESEARCH_LEDGER.md` before continuing any major work.
> Verify claims against code/data/live API before trusting them.
> Last full revision: **2026-06-10** (cleanup/polish session).

## Identity
- **Goal:** consistently profitable trading of short-term BTC Up/Down binary
  prediction-market contracts.
- **Active venue:** Kalshi BTC 15-minute Up/Down, series **KXBTC15M**.
  Target: P(YES resolves 1 at window close); settlement = 60s-average
  **CF Benchmarks BRTI** at close ≥ at open (GTE; ties → YES).
- **Mode:** record-only / paper-first. **Live trading is disabled everywhere by
  default** and requires a separate, explicit, intentionally-unimplemented step.
- **Polymarket BTC 5m (the original leg) was REMOVED on 2026-06-10** — the
  account was parked and the code was dead weight. It lives in git history
  (commit "Remove dormant Polymarket BTC 5m leg"); venue semantics are archived
  under `docs/archive/`.

## Where the project actually stands (honest)
- **Data:** healthy. 770 distinct OFFICIAL-labeled 15m windows with usable
  executable feature rows (gates: 60 backtest / 150 train — both passed long
  ago), ~240k book snapshots, ~700k underlying rows, collector runs continuously.
- **Edge:** none demonstrated. Every taker strategy tested fails to clear the
  ~2.5c round cost (1c spread + ~1.5c taker fee) out-of-sample; the market price
  itself is the best-calibrated forecaster measured (window-ECE ≈ 0.02). The
  conservative lower bound on maker entries is also negative but provably
  pessimistic. **See `RESEARCH_LEDGER.md` for every leg and its verdict — read
  it before proposing a strategy.**
- **Promoted artifacts (paper-only):** fresh pair promoted 2026-06-10 —
  microstructure_logistic + isotonic calibrator fit on the full 770 windows
  (held-out ECE 0.058→0.026, overfit_risk low), replacing the overfit June-3
  pair (which had produced bias-dominated 5–16c edge buffers). SHA-pinned
  manifest in `data/models/paper_promoted/`; promotion is NOT a profitability
  claim; `live_approved=false`.
- **The decision system works:** the confidence-aware edge policy correctly
  blocks ~everything because there is no edge to pass. That is a feature.

## The three open research directions (everything else is concluded)
1. **Sub-second maker/taker microstructure** — UNBLOCKED 2026-06-10: API creds
   were already in `.env`; the read-only market-data WS works (~410 book
   updates/s, 14ms median recv age) and both the hi-res WS recorder and public
   trade-print collection are running. Re-run the maker-entry and reprice-lag
   studies once a few hundred windows of this data exist.
2. **Deep-favorite YES bias** (~+1–2c, consistent across two independent
   studies) — verify on forward data; no new infrastructure needed.
3. **Cross-venue comparison** — needs the Polymarket account funded; revive
   the 5m leg from git history if so.

## Architecture (post-cleanup)
```
src/btc5m/
  config.py, schemas.py, timeutils.py     shared core
  cli.py                                  ~100 kalshi-* commands + shared utils
  data/        underlying.py (Coinbase/Binance REST), recorder.py, deribit_client.py
  labels/      labeling.py (purge/embargo helpers)
  models/      baseline.py, pure_ml.py (stdlib ML), sklearn_models.py
  execution/   risk.py, live_kalshi.py (refuses every order)
  notifications/  pushover -> noop fallback, async queue, explanations
  venues/kalshi/  the entire active system: client, orderbook, features,
                  collector, readiness, labels_audit, model_dataset, splits,
                  train/calibrate/backtest, policy + edge_policy + uncertainty,
                  paper promotion/runtime/experiment, lock + lifecycle,
                  live_readiness (dry-run only), ops, maker_entry,
                  reprice_lag(+hires), residual_alpha, hires/ recorder
tests/         ~600 offline tests; `pytest -q` must stay green
```

## Key invariants (do not weaken)
- Executable prices only (asks for taker entries; never midpoint). Fees always
  subtracted (`KalshiFeeModel`, rate ASSUMED 0.07 taker — verify before live).
- OFFICIAL labels only for training; orphans excluded; purge/embargo on windows;
  `as_of_ms < close_ms` (no lookahead). One authoritative `gate_windows` count.
- Staged artifacts are INACTIVE; the runtime loads only the SHA-pinned paper
  promotion manifest. Promotion/demotion are explicit, audited CLI commands.
- STALE data can never become a PAPER_CANDIDATE (decision-freshness gates).
- `live_submission_allowed` is hard-False everywhere; the live adapter refuses
  unconditionally; kill switch + manual confirmation + paper evidence + risk
  gates are all required and none is implemented to auto-pass.
- Uncertainty buffers are honest measurements — recalibrate to shrink them;
  never delete them.

## Daily operation
```powershell
.\scripts\collect_kalshi_continuous.ps1          # keep data growing (Ctrl-C safe)
python -m btc5m.cli kalshi-ops-status --series KXBTC15M     # one dashboard
python -m btc5m.cli kalshi-data-readiness                   # gate counts
python -m btc5m.cli kalshi-doctor                           # pass/warn/fail
python -m btc5m.cli check-live-disabled                     # safety proof
pytest -q                                                   # ~600 tests, offline
```
Full command reference: `COMMANDS.md`. Operations guide: `RUNBOOK.md`.
Model pipeline details: `MODEL_PIPELINE.md`. Live-safety proof: `LIVE_SAFETY.md`.
Historical audit docs: `docs/archive/`.
