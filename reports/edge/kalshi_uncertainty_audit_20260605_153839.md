# Kalshi calibration-uncertainty audit — KXBTC15M

> READ-ONLY. Recomputed via the production `evaluate_edge`; no trading, no promotion, no paper/live, no artifact mutation. `live_submission_allowed=false`.

- ledger: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\paper\experiments\shadow_clean_30min_20260605_041831_decisions.jsonl`
- cohort: **edge_blocked**  rows: **137**  sides: {'YES': 137}
- calibration rebuild: OK
- promoted model: `paper_model_KXBTC15M_20260603_212839.pkl`  calibrator: `paper_calibrator_KXBTC15M_20260603_212839.pkl`

## Core finding (Part J)
- **Edge identity holds** (`final == raw − required`) for 137/137 rows: **True** — no sign/unit/double-count error.
- Median calibration buffer (recomputed): **15.57c** (row-based). Median model-uncertainty buffer: **5.15c** (ensemble disagreement vs market, NOT the fixed 3c fallback).
- Buffer is **BIAS-DOMINATED**: median bias (mean_pred − mean_actual) = **11.38c**, median sampling (Wilson half-width) = **0.61c** (bias is 95% of the buffer).
- Using DISTINCT WINDOWS instead of rows makes the buffer **smaller** (row 11.99c vs window 10.99c) — row-vs-window overcounting is NOT inflating the buffer; if anything it understates it.
- All selected side YES: **True**; model over-predicts YES in the candidate buckets: **True**.

**Verdict:** the calibration buffer is *mathematically correct* and *bias-dominated* — it reflects a real, large gap between the calibrated YES probability and the realized YES rate in the candidate buckets, not a counting artifact or a bug. It is honestly reduced only by RECALIBRATING the model (so mean_pred ≈ mean_actual), not by deleting the buffer.

## Part A — edge-policy math validation
- raw edge median 10.28c, range (7.137931034482758, 19.185731857318565)
- required edge median 24.35c
- final policy edge median -13.72c, best -3.01c, range (-17.43, -3.01)
- rows with positive final edge: **0** / 137
- reconstructed-vs-stored consistency: identity 137/137 (see CSV `delta_*` columns for residual drift from bucket rebuild).

## Parts B/C — calibration buckets used by the cohort (ROW vs DISTINCT WINDOW)

| bucket | row_n | win_n | rows/win | row YES | win YES | mean_pred | buffer(row) | bias | samp | buffer(win) | top1 win share |
|---|---|---|---|---|---|---|---|---|---|---|---|
| [0.0,0.1) | 3407 | 179 | 19.03 | 0.018 | 0.034 | 0.076 | 6.06 | 5.79 | 0.27 | 5.58 | 0.027 |
| [0.1,0.2) | 7894 | 220 | 35.88 | 0.050 | 0.132 | 0.160 | 11.33 | 11.02 | 0.30 | 5.68 | 0.017 |
| [0.2,0.3) | 4492 | 231 | 19.45 | 0.123 | 0.199 | 0.237 | 11.99 | 11.38 | 0.61 | 6.96 | 0.021 |
| [0.3,0.4) | 5381 | 257 | 20.94 | 0.210 | 0.265 | 0.359 | 15.57 | 14.87 | 0.70 | 12.83 | 0.019 |
| [0.4,0.5) | 4314 | 273 | 15.8 | 0.299 | 0.348 | 0.422 | 13.17 | 12.28 | 0.89 | 10.99 | 0.020 |
| [0.5,0.6) | 1723 | 247 | 6.98 | 0.397 | 0.417 | 0.578 | 19.61 | 18.11 | 1.50 | 20.06 | 0.023 |
| [0.7,0.8) | 10139 | 255 | 39.76 | 0.665 | 0.537 | 0.742 | 8.33 | 7.73 | 0.60 | 24.30 | 0.015 |

_buffer(row) = mean_pred − row_wilson_low (what the policy applies); bias = mean_pred − row_yes; samp = row_yes − row_wilson_low; buffer(win) recomputes the Wilson interval on DISTINCT windows._

## Parts D/E — YES-side bias & model vs market-implied
- cohort sides: {'YES': 137} (all YES => the model only ever finds YES 'underpriced').
- median (model − market-implied) = **10.31c**: the model sits ABOVE the market. In these buckets the realized YES rate is BELOW the market price too, so the market-implied probability is better calibrated than the model — the model's 'edge' is over-prediction.

## Part H — top 20 near-pass rows (closest to passing)

| ticker | s_to_close | side | calib P | yes ask | mkt impl | raw | calib buf | final | reservation |
|---|---|---|---|---|---|---|---|---|---|---|
| KXBTC15M-26JUN050030-30 | 292 | YES | 0.732 | 0.54 | 0.535 | 19.19 | 8.33 | -3.01 | 0.510 |
| KXBTC15M-26JUN050045-45 | 87 | YES | 0.076 | 0.00 | 0.002 | 7.39 | 6.06 | -5.36 | -0.052 |
| KXBTC15M-26JUN050030-30 | 289 | YES | 0.732 | 0.62 | 0.614 | 11.19 | 8.33 | -7.05 | 0.550 |
| KXBTC15M-26JUN050045-45 | 139 | YES | 0.158 | 0.02 | 0.019 | 13.86 | 11.33 | -7.40 | -0.055 |
| KXBTC15M-26JUN050045-45 | 146 | YES | 0.158 | 0.02 | 0.023 | 13.46 | 11.33 | -7.60 | -0.053 |
| KXBTC15M-26JUN050045-45 | 150 | YES | 0.158 | 0.02 | 0.023 | 13.46 | 11.33 | -7.60 | -0.053 |
| KXBTC15M-26JUN050045-45 | 154 | YES | 0.158 | 0.03 | 0.032 | 12.56 | 11.33 | -8.05 | -0.049 |
| KXBTC15M-26JUN050045-45 | 176 | YES | 0.189 | 0.07 | 0.067 | 12.18 | 11.33 | -8.24 | -0.015 |
| KXBTC15M-26JUN050045-45 | 180 | YES | 0.189 | 0.07 | 0.071 | 11.78 | 11.33 | -8.44 | -0.013 |
| KXBTC15M-26JUN050045-45 | 165 | YES | 0.158 | 0.04 | 0.045 | 11.26 | 11.33 | -8.70 | -0.042 |
| KXBTC15M-26JUN050045-45 | 161 | YES | 0.158 | 0.05 | 0.046 | 11.16 | 11.33 | -8.75 | -0.042 |
| KXBTC15M-26JUN050045-45 | 184 | YES | 0.189 | 0.08 | 0.079 | 10.98 | 11.33 | -8.84 | -0.009 |
| KXBTC15M-26JUN050045-45 | 169 | YES | 0.158 | 0.05 | 0.049 | 10.86 | 11.33 | -8.91 | -0.040 |
| KXBTC15M-26JUN050045-45 | 158 | YES | 0.158 | 0.05 | 0.050 | 10.76 | 11.33 | -8.95 | -0.040 |
| KXBTC15M-26JUN050045-45 | 143 | YES | 0.126 | 0.02 | 0.019 | 10.71 | 11.33 | -8.98 | -0.071 |
| KXBTC15M-26JUN050045-45 | 187 | YES | 0.189 | 0.09 | 0.086 | 10.28 | 11.33 | -9.20 | -0.006 |
| KXBTC15M-26JUN050045-45 | 195 | YES | 0.189 | 0.09 | 0.091 | 9.78 | 11.33 | -9.45 | -0.003 |
| KXBTC15M-26JUN050045-45 | 172 | YES | 0.158 | 0.06 | 0.060 | 9.76 | 11.33 | -9.46 | -0.035 |
| KXBTC15M-26JUN050045-45 | 191 | YES | 0.189 | 0.10 | 0.097 | 9.18 | 11.33 | -9.74 | -0.000 |
| KXBTC15M-26JUN050030-30 | 553 | YES | 0.244 | 0.14 | 0.139 | 10.35 | 11.99 | -9.88 | 0.041 |

## Safety
- READ-ONLY: recomputation only; no order, no fill, no paper/live mode, no promotion/demotion.
- No model/calibrator/manifest/active-pointer was modified. Uncertainty buffers were NOT reduced.
- `live_submission_allowed=false`.

