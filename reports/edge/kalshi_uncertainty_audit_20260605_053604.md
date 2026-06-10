# Kalshi calibration-uncertainty audit — KXBTC15M

> READ-ONLY. Recomputed via the production `evaluate_edge`; no trading, no promotion, no paper/live, no artifact mutation. `live_submission_allowed=false`.

- ledger: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\paper\experiments\shadow_clean_30min_20260605_041831_decisions.jsonl`
- cohort: **edge_blocked**  rows: **137**  sides: {'YES': 137}
- calibration rebuild: OK
- promoted model: `paper_model_KXBTC15M_20260603_212839.pkl`  calibrator: `paper_calibrator_KXBTC15M_20260603_212839.pkl`

## Core finding (Part J)
- **Edge identity holds** (`final == raw − required`) for 137/137 rows: **True** — no sign/unit/double-count error.
- Median calibration buffer (recomputed): **15.16c** (row-based). Median model-uncertainty buffer: **5.15c** (ensemble disagreement vs market, NOT the fixed 3c fallback).
- Buffer is **BIAS-DOMINATED**: median bias (mean_pred − mean_actual) = **10.64c**, median sampling (Wilson half-width) = **0.69c** (bias is 94% of the buffer).
- Using DISTINCT WINDOWS instead of rows makes the buffer **smaller** (row 11.32c vs window 11.29c) — row-vs-window overcounting is NOT inflating the buffer; if anything it understates it.
- All selected side YES: **True**; model over-predicts YES in the candidate buckets: **True**.

**Verdict:** the calibration buffer is *mathematically correct* and *bias-dominated* — it reflects a real, large gap between the calibrated YES probability and the realized YES rate in the candidate buckets, not a counting artifact or a bug. It is honestly reduced only by RECALIBRATING the model (so mean_pred ≈ mean_actual), not by deleting the buffer.

## Part A — edge-policy math validation
- raw edge median 10.28c, range (7.137931034482758, 19.185731857318565)
- required edge median 23.95c
- final policy edge median -13.32c, best -5.30c, range (-16.73, -5.30)
- rows with positive final edge: **0** / 137
- reconstructed-vs-stored consistency: identity 137/137 (see CSV `delta_*` columns for residual drift from bucket rebuild).

## Parts B/C — calibration buckets used by the cohort (ROW vs DISTINCT WINDOW)

| bucket | row_n | win_n | rows/win | row YES | win YES | mean_pred | buffer(row) | bias | samp | buffer(win) | top1 win share |
|---|---|---|---|---|---|---|---|---|---|---|---|
| [0.0,0.1) | 3053 | 158 | 19.32 | 0.008 | 0.032 | 0.075 | 6.90 | 6.72 | 0.18 | 5.77 | 0.030 |
| [0.1,0.2) | 6779 | 196 | 34.59 | 0.046 | 0.133 | 0.160 | 11.71 | 11.39 | 0.32 | 5.71 | 0.020 |
| [0.2,0.3) | 3821 | 206 | 18.55 | 0.131 | 0.204 | 0.237 | 11.32 | 10.64 | 0.68 | 6.71 | 0.024 |
| [0.3,0.4) | 4415 | 229 | 19.28 | 0.214 | 0.271 | 0.358 | 15.16 | 14.38 | 0.78 | 12.39 | 0.023 |
| [0.4,0.5) | 3614 | 242 | 14.93 | 0.325 | 0.347 | 0.422 | 10.73 | 9.74 | 0.99 | 11.29 | 0.016 |
| [0.5,0.6) | 1413 | 216 | 6.54 | 0.406 | 0.417 | 0.578 | 18.91 | 17.25 | 1.66 | 20.36 | 0.021 |
| [0.7,0.8) | 7988 | 221 | 36.14 | 0.643 | 0.538 | 0.743 | 10.62 | 9.93 | 0.69 | 24.50 | 0.015 |

_buffer(row) = mean_pred − row_wilson_low (what the policy applies); bias = mean_pred − row_yes; samp = row_yes − row_wilson_low; buffer(win) recomputes the Wilson interval on DISTINCT windows._

## Parts D/E — YES-side bias & model vs market-implied
- cohort sides: {'YES': 137} (all YES => the model only ever finds YES 'underpriced').
- median (model − market-implied) = **10.31c**: the model sits ABOVE the market. In these buckets the realized YES rate is BELOW the market price too, so the market-implied probability is better calibrated than the model — the model's 'edge' is over-prediction.

## Part H — top 20 near-pass rows (closest to passing)

| ticker | s_to_close | side | calib P | yes ask | mkt impl | raw | calib buf | final | reservation |
|---|---|---|---|---|---|---|---|---|---|---|
| KXBTC15M-26JUN050030-30 | 292 | YES | 0.732 | 0.54 | 0.535 | 19.19 | 10.62 | -5.30 | 0.487 |
| KXBTC15M-26JUN050045-45 | 87 | YES | 0.076 | 0.00 | 0.002 | 7.39 | 6.90 | -6.20 | -0.060 |
| KXBTC15M-26JUN050045-45 | 139 | YES | 0.158 | 0.02 | 0.019 | 13.86 | 11.71 | -7.78 | -0.059 |
| KXBTC15M-26JUN050045-45 | 146 | YES | 0.158 | 0.02 | 0.023 | 13.46 | 11.71 | -7.98 | -0.057 |
| KXBTC15M-26JUN050045-45 | 150 | YES | 0.158 | 0.02 | 0.023 | 13.46 | 11.71 | -7.98 | -0.057 |
| KXBTC15M-26JUN050045-45 | 154 | YES | 0.158 | 0.03 | 0.032 | 12.56 | 11.71 | -8.43 | -0.052 |
| KXBTC15M-26JUN050045-45 | 176 | YES | 0.189 | 0.07 | 0.067 | 12.18 | 11.71 | -8.62 | -0.019 |
| KXBTC15M-26JUN050045-45 | 180 | YES | 0.189 | 0.07 | 0.071 | 11.78 | 11.71 | -8.82 | -0.017 |
| KXBTC15M-26JUN050045-45 | 165 | YES | 0.158 | 0.04 | 0.045 | 11.26 | 11.71 | -9.08 | -0.046 |
| KXBTC15M-26JUN050045-45 | 161 | YES | 0.158 | 0.05 | 0.046 | 11.16 | 11.71 | -9.13 | -0.045 |
| KXBTC15M-26JUN050030-30 | 553 | YES | 0.244 | 0.14 | 0.139 | 10.35 | 11.33 | -9.22 | 0.048 |
| KXBTC15M-26JUN050045-45 | 184 | YES | 0.189 | 0.08 | 0.079 | 10.98 | 11.71 | -9.22 | -0.013 |
| KXBTC15M-26JUN050045-45 | 169 | YES | 0.158 | 0.05 | 0.049 | 10.86 | 11.71 | -9.29 | -0.044 |
| KXBTC15M-26JUN050030-30 | 575 | YES | 0.241 | 0.14 | 0.139 | 10.14 | 11.33 | -9.33 | 0.047 |
| KXBTC15M-26JUN050030-30 | 546 | YES | 0.241 | 0.14 | 0.139 | 10.14 | 11.33 | -9.33 | 0.047 |
| KXBTC15M-26JUN050045-45 | 158 | YES | 0.158 | 0.05 | 0.050 | 10.76 | 11.71 | -9.33 | -0.043 |
| KXBTC15M-26JUN050030-30 | 289 | YES | 0.732 | 0.62 | 0.614 | 11.19 | 10.62 | -9.34 | 0.527 |
| KXBTC15M-26JUN050045-45 | 143 | YES | 0.126 | 0.02 | 0.019 | 10.71 | 11.71 | -9.35 | -0.075 |
| KXBTC15M-26JUN050030-30 | 579 | YES | 0.220 | 0.12 | 0.119 | 9.95 | 11.33 | -9.41 | 0.026 |
| KXBTC15M-26JUN050045-45 | 187 | YES | 0.189 | 0.09 | 0.086 | 10.28 | 11.71 | -9.58 | -0.010 |

## Safety
- READ-ONLY: recomputation only; no order, no fill, no paper/live mode, no promotion/demotion.
- No model/calibrator/manifest/active-pointer was modified. Uncertainty buffers were NOT reduced.
- `live_submission_allowed=false`.

