# Kalshi calibration-uncertainty audit — KXBTC15M

> READ-ONLY. Recomputed via the production `evaluate_edge`; no trading, no promotion, no paper/live, no artifact mutation. `live_submission_allowed=false`.

- ledger: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\paper\experiments\shadow_clean_30min_20260605_041831_decisions.jsonl`
- cohort: **edge_blocked**  rows: **137**  sides: {'YES': 137}
- calibration rebuild: OK
- promoted model: `paper_model_KXBTC15M_20260603_212839.pkl`  calibrator: `paper_calibrator_KXBTC15M_20260603_212839.pkl`

## Core finding (Part J)
- **Edge identity holds** (`final == raw − required`) for 137/137 rows: **True** — no sign/unit/double-count error.
- Median calibration buffer (recomputed): **8.33c** (row-based). Median model-uncertainty buffer: **5.15c** (ensemble disagreement vs market, NOT the fixed 3c fallback).
- Buffer is **BIAS-DOMINATED**: median bias (mean_pred − mean_actual) = **7.64c**, median sampling (Wilson half-width) = **0.52c** (bias is 96% of the buffer).
- Using DISTINCT WINDOWS instead of rows makes the buffer **smaller** (row 7.92c vs window 4.58c) — row-vs-window overcounting is NOT inflating the buffer; if anything it understates it.
- All selected side YES: **True**; model over-predicts YES in the candidate buckets: **True**.

**Verdict:** the calibration buffer is *mathematically correct* and *bias-dominated* — it reflects a real, large gap between the calibrated YES probability and the realized YES rate in the candidate buckets, not a counting artifact or a bug. It is honestly reduced only by RECALIBRATING the model (so mean_pred ≈ mean_actual), not by deleting the buffer.

## Part A — edge-policy math validation
- raw edge median 10.28c, range (7.137931034482758, 19.185731857318565)
- required edge median 17.40c
- final policy edge median -6.48c, best 0.58c, range (-14.09, 0.58)
- rows with positive final edge: **1** / 137
- reconstructed-vs-stored consistency: identity 137/137 (see CSV `delta_*` columns for residual drift from bucket rebuild).

## Parts B/C — calibration buckets used by the cohort (ROW vs DISTINCT WINDOW)

| bucket | row_n | win_n | rows/win | row YES | win YES | mean_pred | buffer(row) | bias | samp | buffer(win) | top1 win share |
|---|---|---|---|---|---|---|---|---|---|---|---|
| [0.0,0.1) | 9335 | 325 | 28.72 | 0.028 | 0.040 | 0.073 | 4.68 | 4.47 | 0.21 | 4.58 | 0.012 |
| [0.1,0.2) | 15280 | 393 | 38.88 | 0.083 | 0.142 | 0.159 | 7.92 | 7.64 | 0.28 | 4.00 | 0.009 |
| [0.2,0.3) | 8657 | 421 | 20.56 | 0.173 | 0.238 | 0.237 | 6.92 | 6.40 | 0.52 | 2.55 | 0.012 |
| [0.3,0.4) | 10850 | 462 | 23.48 | 0.282 | 0.314 | 0.359 | 8.33 | 7.78 | 0.55 | 7.24 | 0.012 |
| [0.4,0.5) | 8664 | 486 | 17.83 | 0.343 | 0.407 | 0.422 | 8.56 | 7.91 | 0.65 | 4.29 | 0.012 |
| [0.5,0.6) | 3597 | 446 | 8.07 | 0.426 | 0.464 | 0.578 | 16.27 | 15.21 | 1.05 | 14.40 | 0.011 |
| [0.7,0.8) | 20523 | 470 | 43.67 | 0.700 | 0.585 | 0.743 | 4.74 | 4.33 | 0.41 | 18.54 | 0.008 |

_buffer(row) = mean_pred − row_wilson_low (what the policy applies); bias = mean_pred − row_yes; samp = row_yes − row_wilson_low; buffer(win) recomputes the Wilson interval on DISTINCT windows._

## Parts D/E — YES-side bias & model vs market-implied
- cohort sides: {'YES': 137} (all YES => the model only ever finds YES 'underpriced').
- median (model − market-implied) = **10.31c**: the model sits ABOVE the market. In these buckets the realized YES rate is BELOW the market price too, so the market-implied probability is better calibrated than the model — the model's 'edge' is over-prediction.

## Part H — top 20 near-pass rows (closest to passing)

| ticker | s_to_close | side | calib P | yes ask | mkt impl | raw | calib buf | final | reservation |
|---|---|---|---|---|---|---|---|---|---|---|
| KXBTC15M-26JUN050030-30 | 292 | YES | 0.732 | 0.54 | 0.535 | 19.19 | 4.74 | 0.58 | 0.546 |
| KXBTC15M-26JUN050030-30 | 289 | YES | 0.732 | 0.62 | 0.614 | 11.19 | 4.74 | -3.46 | 0.585 |
| KXBTC15M-26JUN050045-45 | 87 | YES | 0.076 | 0.00 | 0.002 | 7.39 | 4.68 | -3.98 | -0.038 |
| KXBTC15M-26JUN050045-45 | 139 | YES | 0.158 | 0.02 | 0.019 | 13.86 | 7.92 | -3.99 | -0.021 |
| KXBTC15M-26JUN050045-45 | 146 | YES | 0.158 | 0.02 | 0.023 | 13.46 | 7.92 | -4.19 | -0.019 |
| KXBTC15M-26JUN050045-45 | 150 | YES | 0.158 | 0.02 | 0.023 | 13.46 | 7.92 | -4.20 | -0.019 |
| KXBTC15M-26JUN050045-45 | 771 | YES | 0.380 | 0.22 | 0.218 | 16.03 | 8.33 | -4.42 | 0.176 |
| KXBTC15M-26JUN050045-45 | 154 | YES | 0.158 | 0.03 | 0.032 | 12.56 | 7.92 | -4.65 | -0.014 |
| KXBTC15M-26JUN050030-30 | 553 | YES | 0.244 | 0.14 | 0.139 | 10.35 | 6.92 | -4.81 | 0.092 |
| KXBTC15M-26JUN050045-45 | 176 | YES | 0.189 | 0.07 | 0.067 | 12.18 | 7.92 | -4.84 | 0.019 |
| KXBTC15M-26JUN050030-30 | 575 | YES | 0.241 | 0.14 | 0.139 | 10.14 | 6.92 | -4.92 | 0.091 |
| KXBTC15M-26JUN050030-30 | 546 | YES | 0.241 | 0.14 | 0.139 | 10.14 | 6.92 | -4.92 | 0.091 |
| KXBTC15M-26JUN050045-45 | 764 | YES | 0.380 | 0.23 | 0.228 | 15.03 | 8.33 | -4.93 | 0.181 |
| KXBTC15M-26JUN050045-45 | 643 | YES | 0.380 | 0.23 | 0.228 | 15.03 | 8.33 | -4.93 | 0.181 |
| KXBTC15M-26JUN050045-45 | 613 | YES | 0.380 | 0.23 | 0.228 | 15.03 | 8.33 | -4.93 | 0.181 |
| KXBTC15M-26JUN050100-00 | 722 | YES | 0.380 | 0.23 | 0.228 | 15.03 | 8.33 | -4.93 | 0.181 |
| KXBTC15M-26JUN050100-00 | 653 | YES | 0.329 | 0.18 | 0.178 | 14.90 | 8.33 | -4.97 | 0.130 |
| KXBTC15M-26JUN050030-30 | 579 | YES | 0.220 | 0.12 | 0.119 | 9.95 | 6.92 | -5.00 | 0.070 |
| KXBTC15M-26JUN050045-45 | 180 | YES | 0.189 | 0.07 | 0.071 | 11.78 | 7.92 | -5.04 | 0.021 |
| KXBTC15M-26JUN050045-45 | 646 | YES | 0.380 | 0.23 | 0.225 | 15.03 | 8.33 | -5.04 | 0.180 |

## Safety
- READ-ONLY: recomputation only; no order, no fill, no paper/live mode, no promotion/demotion.
- No model/calibrator/manifest/active-pointer was modified. Uncertainty buffers were NOT reduced.
- `live_submission_allowed=false`.

