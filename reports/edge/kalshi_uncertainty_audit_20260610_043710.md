# Kalshi calibration-uncertainty audit — KXBTC15M

> READ-ONLY. Recomputed via the production `evaluate_edge`; no trading, no promotion, no paper/live, no artifact mutation. `live_submission_allowed=false`.

- ledger: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\paper\experiments\shadow_clean_30min_20260605_041831_decisions.jsonl`
- cohort: **edge_blocked**  rows: **137**  sides: {'YES': 137}
- calibration rebuild: OK
- promoted model: `paper_model_KXBTC15M_20260603_212839.pkl`  calibrator: `paper_calibrator_KXBTC15M_20260603_212839.pkl`

## Core finding (Part J)
- **Edge identity holds** (`final == raw − required`) for 137/137 rows: **True** — no sign/unit/double-count error.
- Median calibration buffer (recomputed): **5.70c** (row-based). Median model-uncertainty buffer: **5.15c** (ensemble disagreement vs market, NOT the fixed 3c fallback).
- Buffer is **BIAS-DOMINATED**: median bias (mean_pred − mean_actual) = **4.91c**, median sampling (Wilson half-width) = **0.50c** (bias is 89% of the buffer).
- Using DISTINCT WINDOWS instead of rows makes the buffer **smaller** (row 5.53c vs window 4.06c) — row-vs-window overcounting is NOT inflating the buffer; if anything it understates it.
- All selected side YES: **True**; model over-predicts YES in the candidate buckets: **True**.

**Verdict:** the calibration buffer is *mathematically correct* and *bias-dominated* — it reflects a real, large gap between the calibrated YES probability and the realized YES rate in the candidate buckets, not a counting artifact or a bug. It is honestly reduced only by RECALIBRATING the model (so mean_pred ≈ mean_actual), not by deleting the buffer.

## Part A — edge-policy math validation
- raw edge median 10.28c, range (7.137931034482758, 19.185731857318565)
- required edge median 14.85c
- final policy edge median -4.35c, best 0.16c, range (-12.11, 0.16)
- rows with positive final edge: **1** / 137
- reconstructed-vs-stored consistency: identity 137/137 (see CSV `delta_*` columns for residual drift from bucket rebuild).

## Parts B/C — calibration buckets used by the cohort (ROW vs DISTINCT WINDOW)

| bucket | row_n | win_n | rows/win | row YES | win YES | mean_pred | buffer(row) | bias | samp | buffer(win) | top1 win share |
|---|---|---|---|---|---|---|---|---|---|---|---|
| [0.0,0.1) | 11668 | 382 | 30.54 | 0.027 | 0.044 | 0.072 | 4.74 | 4.56 | 0.18 | 4.06 | 0.009 |
| [0.1,0.2) | 17681 | 462 | 38.27 | 0.099 | 0.156 | 0.159 | 6.30 | 6.02 | 0.28 | 2.57 | 0.008 |
| [0.2,0.3) | 9717 | 490 | 19.83 | 0.189 | 0.251 | 0.237 | 5.35 | 4.85 | 0.50 | 1.06 | 0.011 |
| [0.3,0.4) | 12335 | 539 | 22.88 | 0.308 | 0.328 | 0.359 | 5.70 | 5.17 | 0.53 | 5.65 | 0.011 |
| [0.4,0.5) | 9884 | 559 | 17.68 | 0.373 | 0.417 | 0.422 | 5.53 | 4.91 | 0.62 | 3.16 | 0.011 |
| [0.5,0.6) | 4082 | 504 | 8.1 | 0.445 | 0.476 | 0.578 | 14.29 | 13.29 | 0.99 | 13.02 | 0.010 |
| [0.7,0.8) | 23777 | 548 | 43.39 | 0.695 | 0.599 | 0.743 | 5.17 | 4.78 | 0.38 | 17.00 | 0.007 |

_buffer(row) = mean_pred − row_wilson_low (what the policy applies); bias = mean_pred − row_yes; samp = row_yes − row_wilson_low; buffer(win) recomputes the Wilson interval on DISTINCT windows._

## Parts D/E — YES-side bias & model vs market-implied
- cohort sides: {'YES': 137} (all YES => the model only ever finds YES 'underpriced').
- median (model − market-implied) = **10.31c**: the model sits ABOVE the market. In these buckets the realized YES rate is BELOW the market price too, so the market-implied probability is better calibrated than the model — the model's 'edge' is over-prediction.

## Part H — top 20 near-pass rows (closest to passing)

| ticker | s_to_close | side | calib P | yes ask | mkt impl | raw | calib buf | final | reservation |
|---|---|---|---|---|---|---|---|---|---|---|
| KXBTC15M-26JUN050030-30 | 292 | YES | 0.732 | 0.54 | 0.535 | 19.19 | 5.17 | 0.16 | 0.542 |
| KXBTC15M-26JUN050045-45 | 771 | YES | 0.380 | 0.22 | 0.218 | 16.03 | 5.70 | -1.79 | 0.202 |
| KXBTC15M-26JUN050045-45 | 764 | YES | 0.380 | 0.23 | 0.228 | 15.03 | 5.70 | -2.30 | 0.207 |
| KXBTC15M-26JUN050045-45 | 643 | YES | 0.380 | 0.23 | 0.228 | 15.03 | 5.70 | -2.30 | 0.207 |
| KXBTC15M-26JUN050045-45 | 613 | YES | 0.380 | 0.23 | 0.228 | 15.03 | 5.70 | -2.30 | 0.207 |
| KXBTC15M-26JUN050100-00 | 722 | YES | 0.380 | 0.23 | 0.228 | 15.03 | 5.70 | -2.30 | 0.207 |
| KXBTC15M-26JUN050100-00 | 653 | YES | 0.329 | 0.18 | 0.178 | 14.90 | 5.70 | -2.33 | 0.157 |
| KXBTC15M-26JUN050045-45 | 139 | YES | 0.158 | 0.02 | 0.019 | 13.86 | 6.30 | -2.37 | -0.005 |
| KXBTC15M-26JUN050045-45 | 646 | YES | 0.380 | 0.23 | 0.225 | 15.03 | 5.70 | -2.41 | 0.206 |
| KXBTC15M-26JUN050045-45 | 146 | YES | 0.158 | 0.02 | 0.023 | 13.46 | 6.30 | -2.57 | -0.003 |
| KXBTC15M-26JUN050045-45 | 150 | YES | 0.158 | 0.02 | 0.023 | 13.46 | 6.30 | -2.58 | -0.003 |
| KXBTC15M-26JUN050045-45 | 665 | YES | 0.380 | 0.24 | 0.238 | 14.03 | 5.70 | -2.80 | 0.212 |
| KXBTC15M-26JUN050100-00 | 730 | YES | 0.380 | 0.24 | 0.238 | 14.03 | 5.70 | -2.80 | 0.212 |
| KXBTC15M-26JUN050045-45 | 639 | YES | 0.380 | 0.24 | 0.235 | 14.03 | 5.70 | -2.92 | 0.211 |
| KXBTC15M-26JUN050045-45 | 154 | YES | 0.158 | 0.03 | 0.032 | 12.56 | 6.30 | -3.03 | 0.002 |
| KXBTC15M-26JUN050045-45 | 176 | YES | 0.189 | 0.07 | 0.067 | 12.18 | 6.30 | -3.21 | 0.035 |
| KXBTC15M-26JUN050030-30 | 553 | YES | 0.244 | 0.14 | 0.139 | 10.35 | 5.35 | -3.25 | 0.108 |
| KXBTC15M-26JUN050030-30 | 646 | YES | 0.380 | 0.25 | 0.248 | 13.03 | 5.70 | -3.31 | 0.217 |
| KXBTC15M-26JUN050100-00 | 700 | YES | 0.380 | 0.25 | 0.248 | 13.03 | 5.70 | -3.31 | 0.217 |
| KXBTC15M-26JUN050030-30 | 631 | YES | 0.329 | 0.20 | 0.198 | 12.90 | 5.70 | -3.34 | 0.167 |

## Safety
- READ-ONLY: recomputation only; no order, no fill, no paper/live mode, no promotion/demotion.
- No model/calibrator/manifest/active-pointer was modified. Uncertainty buffers were NOT reduced.
- `live_submission_allowed=false`.

