# Kalshi calibration-uncertainty audit — KXBTC15M

> READ-ONLY. Recomputed via the production `evaluate_edge`; no trading, no promotion, no paper/live, no artifact mutation. `live_submission_allowed=false`.

- ledger: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\paper\experiments\shadow_compare_20260605_064333_decisions.jsonl`
- cohort: **edge_blocked**  rows: **0**  sides: {}
- calibration rebuild: OK
- promoted model: `paper_model_KXBTC15M_20260603_212839.pkl`  calibrator: `paper_calibrator_KXBTC15M_20260603_212839.pkl`

## Core finding (Part J)
- **Edge identity holds** (`final == raw − required`) for 0/0 rows: **False** — no sign/unit/double-count error.
- Median calibration buffer (recomputed): **Nonec** (row-based). Median model-uncertainty buffer: **Nonec** (ensemble disagreement vs market, NOT the fixed 3c fallback).
- Buffer is **sampling-influenced**: median bias (mean_pred − mean_actual) = **Nonec**, median sampling (Wilson half-width) = **Nonec** (bias is 0% of the buffer).
- Using DISTINCT WINDOWS instead of rows makes the buffer **smaller** (row Nonec vs window Nonec) — row-vs-window overcounting is NOT inflating the buffer; if anything it understates it.
- All selected side YES: **True**; model over-predicts YES in the candidate buckets: **False**.

**Verdict:** the calibration buffer is *mathematically correct* and *bias-dominated* — it reflects a real, large gap between the calibrated YES probability and the realized YES rate in the candidate buckets, not a counting artifact or a bug. It is honestly reduced only by RECALIBRATING the model (so mean_pred ≈ mean_actual), not by deleting the buffer.

## Part A — edge-policy math validation
- raw edge median Nonec, range (None, None)
- required edge median Nonec
- final policy edge median Nonec, best Nonec, range (None, None)
- rows with positive final edge: **0** / 0
- reconstructed-vs-stored consistency: identity 0/0 (see CSV `delta_*` columns for residual drift from bucket rebuild).

## Parts B/C — calibration buckets used by the cohort (ROW vs DISTINCT WINDOW)

| bucket | row_n | win_n | rows/win | row YES | win YES | mean_pred | buffer(row) | bias | samp | buffer(win) | top1 win share |
|---|---|---|---|---|---|---|---|---|---|---|---|

_buffer(row) = mean_pred − row_wilson_low (what the policy applies); bias = mean_pred − row_yes; samp = row_yes − row_wilson_low; buffer(win) recomputes the Wilson interval on DISTINCT windows._

## Parts D/E — YES-side bias & model vs market-implied
- cohort sides: {} (all YES => the model only ever finds YES 'underpriced').
- median (model − market-implied) = **Nonec**: the model sits ABOVE the market. In these buckets the realized YES rate is BELOW the market price too, so the market-implied probability is better calibrated than the model — the model's 'edge' is over-prediction.

## Part H — top 20 near-pass rows (closest to passing)

| ticker | s_to_close | side | calib P | yes ask | mkt impl | raw | calib buf | final | reservation |
|---|---|---|---|---|---|---|---|---|---|---|

## Safety
- READ-ONLY: recomputation only; no order, no fill, no paper/live mode, no promotion/demotion.
- No model/calibrator/manifest/active-pointer was modified. Uncertainty buffers were NOT reduced.
- `live_submission_allowed=false`.

