# LIVE_SAFETY — Kalshi BTC 15m

**Live trading is DISABLED by default and is impossible without a separate, explicit
future enablement step.** This document is the single reference for the safety model.
Nothing in the current build can submit or cancel a real order.

## Defaults (all safe)
| Setting | Default | Meaning |
|---|---|---|
| `TRADING_MODE` | `paper` | record-only / paper |
| `LIVE_TRADING_ENABLED` | `false` | live never permitted |
| `KILL_SWITCH_ENABLED` | `true` | all orders rejected |
| `REQUIRE_MANUAL_CONFIRMATION` | `true` | needs a confirmation handler (none wired) |
| `KALSHI_LIVE_SUBMIT_ENABLED` | `false` | submit path disabled |
| `KALSHI_LIVE_DRY_RUN_ONLY` | `true` | dry-run payloads only |
| `KALSHI_ALLOW_MARKET_ORDERS` | `false` | limit + FOK/IOC only |
| `KALSHI_PAPER_POLICY_ENABLED` | `false` | policy off |
| `KALSHI_LOCK_MODULE_ENABLED` | `false` | lock module off |

## Why no order can be submitted
- `LiveKalshiExecutionAdapter.submit()` / `cancel()` **always return a structured
  refusal and issue no HTTP** (tested: `urlopen` call count is 0 under default config).
  There is a hard `_http_mutation` guard. (The legacy Polymarket adapter was removed 2026-06-10.)
- `live_submission_allowed` is a hard-`False` property on `LiveReadinessConfig`,
  `PaperPolicyConfig`, `LockConfig`, every `PolicyDecision`, every `LockDecision`,
  every dry-run order payload, and every order intent.
- There is **no `LIVE_CANDIDATE`** state and no `SUBMITTED` / `LIVE_FILLED` state.
- Market orders are rejected; only limit + FOK/IOC dry-run payloads are built.

## Why PAPER_CANDIDATE cannot fire from a bad model
The policy requires ALL of: policy enabled · model trained · model NON-diagnostic ·
calibrator valid + non-diagnostic · backtest evidence valid above gate · calibrated
probability present · executable asks/valid book · net & raw edge ≥ thresholds ·
price ≤ reservation & cap · fresh book/underlying · spread/depth OK · time-in-window ·
risk limits OK. A hard Up/Down class alone never trades. Today every model is
`NON_TRADABLE_DIAGNOSTIC_ONLY` and uncalibrated ⇒ policy REJECTS.

## Credentials & secrets
- Kalshi auth (`KALSHI_KEY_ID` + `KALSHI_PRIVATE_KEY_PATH`) is env-only; the RSA key
  lives in a gitignored local file. **No key material, passphrase, or auth header is
  ever read or printed.** Credential preflight reports presence/readability only.
- Missing credentials are BLOCKERS, never chat prompts. Pushover missing ⇒ Noop.
- Live-readiness audit log (`data/audit/kalshi_live_readiness_*.jsonl`) is sanitized.

## What is NOT present (by design)
- No flat-position same-market arbitrage scanner. The lock module only manages an
  EXISTING paper position (post-entry); it never scans flat markets for YES+NO<1.
- No authenticated private reads / WS streaming (scaffold; needs Kalshi API credentials).

## Verify anytime (read-only)
```powershell
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-safety-status --series KXBTC15M
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-live-blockers --series KXBTC15M
.\.venv\Scripts\python.exe -m btc5m.cli check-live-disabled
```
Expected: `LIVE TRADING DISABLED`, every blocker listed, both adapters refuse.

## Enabling live LATER (separate explicit step — not now)
Would require, deliberately and together: a trained + calibrated + non-diagnostic
model with edge-positive executable backtest; real paper evidence + a manual
`data/models/kalshi_live_approval.json` (`evidence_approved_for_live=true`);
`cryptography` installed + Kalshi auth; flipping mode=live + `LIVE_TRADING_ENABLED` +
`KALSHI_LIVE_SUBMIT_ENABLED`, kill switch off, a manual-confirmation handler, and
concrete risk limits — plus implementing the actual signed submit path (a future
prompt). None of this is done here.
