# Kalshi calibration-uncertainty audit — KXBTC15M

> READ-ONLY. Recomputed via the production `evaluate_edge`; no trading, no promotion, no paper/live, no artifact mutation. `live_submission_allowed=false`.

- ledger: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\paper\experiments\shadow_clean_30min_20260605_041831_decisions.jsonl`
- cohort: **edge_blocked**  rows: **137**  sides: {'YES': 137}
- calibration rebuild: OK
- promoted model: `paper_model_KXBTC15M_20260603_212839.pkl`  calibrator: `paper_calibrator_KXBTC15M_20260603_212839.pkl`

## Core finding (Part J)
- **Edge identity holds** (`final == raw − required`) for 137/137 rows: **True** — no sign/unit/double-count error.
- Median calibration buffer (recomputed): **15.51c** (row-based). Median model-uncertainty buffer: **5.15c** (ensemble disagreement vs market, NOT the fixed 3c fallback).
- Buffer is **BIAS-DOMINATED**: median bias (mean_pred − mean_actual) = **10.78c**, median sampling (Wilson half-width) = **0.69c** (bias is 94% of the buffer).
- Using DISTINCT WINDOWS instead of rows makes the buffer **smaller** (row 11.47c vs window 11.68c) — row-vs-window overcounting is NOT inflating the buffer; if anything it understates it.
- All selected side YES: **True**; model over-predicts YES in the candidate buckets: **True**.

**Verdict:** the calibration buffer is *mathematically correct* and *bias-dominated* — it reflects a real, large gap between the calibrated YES probability and the realized YES rate in the candidate buckets, not a counting artifact or a bug. It is honestly reduced only by RECALIBRATING the model (so mean_pred ≈ mean_actual), not by deleting the buffer.

## Part A — edge-policy math validation
- raw edge median 10.28c, range (7.137931034482758, 19.185731857318565)
- required edge median 24.29c
- final policy edge median -13.66c, best -5.99c, range (-17.39, -5.99)
- rows with positive final edge: **0** / 137
- reconstructed-vs-stored consistency: identity 137/137 (see CSV `delta_*` columns for residual drift from bucket rebuild).

## Parts B/C — calibration buckets used by the cohort (ROW vs DISTINCT WINDOW)

| bucket | row_n | win_n | rows/win | row YES | win YES | mean_pred | buffer(row) | bias | samp | buffer(win) | top1 win share |
|---|---|---|---|---|---|---|---|---|---|---|---|
| [0.0,0.1) | 3083 | 161 | 19.15 | 0.008 | 0.031 | 0.075 | 6.91 | 6.73 | 0.18 | 5.81 | 0.030 |
| [0.1,0.2) | 6906 | 199 | 34.7 | 0.045 | 0.131 | 0.160 | 11.79 | 11.48 | 0.31 | 5.87 | 0.020 |
| [0.2,0.3) | 3865 | 209 | 18.49 | 0.129 | 0.201 | 0.237 | 11.46 | 10.78 | 0.68 | 6.95 | 0.024 |
| [0.3,0.4) | 4486 | 232 | 19.34 | 0.211 | 0.267 | 0.358 | 15.51 | 14.74 | 0.77 | 12.71 | 0.023 |
| [0.4,0.5) | 3701 | 245 | 15.11 | 0.317 | 0.343 | 0.422 | 11.47 | 10.50 | 0.97 | 11.68 | 0.015 |
| [0.5,0.6) | 1437 | 219 | 6.56 | 0.399 | 0.411 | 0.578 | 19.57 | 17.93 | 1.64 | 20.89 | 0.021 |
| [0.7,0.8) | 8075 | 224 | 36.05 | 0.637 | 0.531 | 0.743 | 11.31 | 10.62 | 0.69 | 25.19 | 0.015 |

_buffer(row) = mean_pred − row_wilson_low (what the policy applies); bias = mean_pred − row_yes; samp = row_yes − row_wilson_low; buffer(win) recomputes the Wilson interval on DISTINCT windows._

## Parts D/E — YES-side bias & model vs market-implied
- cohort sides: {'YES': 137} (all YES => the model only ever finds YES 'underpriced').
- median (model − market-implied) = **10.31c**: the model sits ABOVE the market. In these buckets the realized YES rate is BELOW the market price too, so the market-implied probability is better calibrated than the model — the model's 'edge' is over-prediction.

## Part H — top 20 near-pass rows (closest to passing)

| ticker | s_to_close | side | calib P | yes ask | mkt impl | raw | calib buf | final | reservation |
|---|---|---|---|---|---|---|---|---|---|---|
| KXBTC15M-26JUN050030-30 | 292 | YES | 0.732 | 0.54 | 0.535 | 19.19 | 11.31 | -5.99 | 0.480 |
| KXBTC15M-26JUN050045-45 | 87 | YES | 0.076 | 0.00 | 0.002 | 7.39 | 6.91 | -6.21 | -0.060 |
| KXBTC15M-26JUN050045-45 | 139 | YES | 0.158 | 0.02 | 0.019 | 13.86 | 11.79 | -7.86 | -0.060 |
| KXBTC15M-26JUN050045-45 | 146 | YES | 0.158 | 0.02 | 0.023 | 13.46 | 11.79 | -8.06 | -0.058 |
| KXBTC15M-26JUN050045-45 | 150 | YES | 0.158 | 0.02 | 0.023 | 13.46 | 11.79 | -8.07 | -0.058 |
| KXBTC15M-26JUN050045-45 | 154 | YES | 0.158 | 0.03 | 0.032 | 12.56 | 11.79 | -8.52 | -0.053 |
| KXBTC15M-26JUN050045-45 | 176 | YES | 0.189 | 0.07 | 0.067 | 12.18 | 11.79 | -8.71 | -0.020 |
| KXBTC15M-26JUN050045-45 | 180 | YES | 0.189 | 0.07 | 0.071 | 11.78 | 11.79 | -8.91 | -0.018 |
| KXBTC15M-26JUN050045-45 | 165 | YES | 0.158 | 0.04 | 0.045 | 11.26 | 11.79 | -9.16 | -0.047 |
| KXBTC15M-26JUN050045-45 | 161 | YES | 0.158 | 0.05 | 0.046 | 11.16 | 11.79 | -9.21 | -0.046 |
| KXBTC15M-26JUN050045-45 | 184 | YES | 0.189 | 0.08 | 0.079 | 10.98 | 11.79 | -9.31 | -0.014 |
| KXBTC15M-26JUN050030-30 | 553 | YES | 0.244 | 0.14 | 0.139 | 10.35 | 11.46 | -9.35 | 0.046 |
| KXBTC15M-26JUN050045-45 | 169 | YES | 0.158 | 0.05 | 0.049 | 10.86 | 11.79 | -9.38 | -0.045 |
| KXBTC15M-26JUN050045-45 | 158 | YES | 0.158 | 0.05 | 0.050 | 10.76 | 11.79 | -9.42 | -0.044 |
| KXBTC15M-26JUN050045-45 | 143 | YES | 0.126 | 0.02 | 0.019 | 10.71 | 11.79 | -9.44 | -0.075 |
| KXBTC15M-26JUN050030-30 | 575 | YES | 0.241 | 0.14 | 0.139 | 10.14 | 11.46 | -9.46 | 0.045 |
| KXBTC15M-26JUN050030-30 | 546 | YES | 0.241 | 0.14 | 0.139 | 10.14 | 11.46 | -9.46 | 0.045 |
| KXBTC15M-26JUN050030-30 | 579 | YES | 0.220 | 0.12 | 0.119 | 9.95 | 11.46 | -9.54 | 0.025 |
| KXBTC15M-26JUN050045-45 | 187 | YES | 0.189 | 0.09 | 0.086 | 10.28 | 11.79 | -9.66 | -0.011 |
| KXBTC15M-26JUN050030-30 | 590 | YES | 0.244 | 0.15 | 0.149 | 9.35 | 11.46 | -9.86 | 0.051 |

## Safety
- READ-ONLY: recomputation only; no order, no fill, no paper/live mode, no promotion/demotion.
- No model/calibrator/manifest/active-pointer was modified. Uncertainty buffers were NOT reduced.
- `live_submission_allowed=false`.

