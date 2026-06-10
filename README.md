# btc5m — Kalshi BTC 15-Minute Up/Down Probability & Execution Research System

A record-only / paper-first system for short-term BTC binary prediction-market
contracts. Active venue: **Kalshi BTC 15m Up/Down (series KXBTC15M)**. It
estimates the calibrated settlement probability P(YES resolves 1 at window
close), prices contracts against executable bids/asks net of fees, and gates
every decision behind freshness, depth, calibration, uncertainty, and risk
checks. **Live trading is disabled everywhere by default** — the live adapter
refuses every order unconditionally in this build.

> **Start here:** `PROJECT_STATE.md` (current state) and `RESEARCH_LEDGER.md`
> (every hypothesis tested and its verdict). Operations: `RUNBOOK.md`.
> All commands: `COMMANDS.md`. Why nothing can submit: `LIVE_SAFETY.md`.

## Honest status (2026-06-10)

- **Pipeline:** healthy. 770 OFFICIAL-labeled, feature-backed 15m windows;
  continuous collector records Kalshi books + Coinbase/Binance underlying
  microstructure (+ optional Deribit vol) into point-in-time, no-lookahead
  feature rows; ~600 offline tests pass.
- **Edge:** none demonstrated yet. KXBTC15M is tight (median spread ~1c, taker
  fee ~1.5c) and the market price is the best-calibrated forecaster measured.
  Direct models, residual-over-market models, stale-quote sniping, and the
  conservative lower bound on maker entries all fail to clear costs
  out-of-sample. The ledger documents each verdict and the three directions
  still open (sub-second WS microstructure, deep-favorite YES bias,
  cross-venue).
- **Promoted artifacts (paper-only):** a freshly trained + isotonic-calibrated
  pair (held-out ECE 0.026, overfit risk low) is promoted via a SHA-pinned
  manifest for shadow/paper experiments. Promotion is not a profitability claim.

## Quick start

```powershell
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e ".[models]"
copy .env.example .env
pytest -q                                            # offline suite
python -m btc5m.cli check-live-disabled              # safety proof

# collect (read-only; Ctrl-C safe)
.\scripts\collect_kalshi_continuous.ps1

# daily visibility (read-only)
python -m btc5m.cli kalshi-ops-status --series KXBTC15M
python -m btc5m.cli kalshi-data-readiness
python -m btc5m.cli kalshi-doctor
```

## Layout

```
src/btc5m/venues/kalshi/   the active system (client, books, features, collector,
                           dataset/training/calibration/backtest, edge policy,
                           paper promotion + experiments, lock/lifecycle,
                           live-readiness dry-run, ops, research studies, hires/)
src/btc5m/{data,labels,models,execution,notifications}/   shared core
tests/                     offline pytest suite
data/                      JSONL records, labels, features, models (gitignored)
reports/                   generated markdown/CSV reports (mostly gitignored)
docs/archive/              historical state/audit documents
```

The original Polymarket BTC 5m leg was removed on 2026-06-10 after the venue
was parked; it is recoverable from git history if cross-venue work resumes.

## Safety invariants

Executable prices only (never midpoint) · fees always subtracted · OFFICIAL
labels only, purged/embargoed windows, no lookahead · staged artifacts inactive
until explicitly promoted (SHA-pinned, audited) · stale data can never become a
candidate · uncertainty buffers are measurements, never deleted ·
`live_submission_allowed` hard-False everywhere · kill switch + manual
confirmation + paper evidence + risk gates all required for any future live step.
