# Kalshi calibration report — KXBTC15M

- method: isotonic
- tradable: **False**  diagnostic_only: True
- model_schema_version: 1
- gate_windows: 95 / calibration gate 150
- split: train=48 calib=24 test=21 embargo=1 (windows; purged/embargoed; held-out TEST)

## Calibration metrics (TEST windows; diagnostic — not a profitability claim)
| metric | before (raw) | after (calibrated) |
|---|---|---|
| n | 84 | 84 |
| brier | 0.1741 | 0.1774 |
| log_loss | 0.5012 | 0.5015 |
| ECE | 0.1474 | 0.1169 |
| slope | 0.8161 | 1.0193 |
| intercept | 0.1306 | 0.1091 |

## Reliability buckets (after calibration)
| bucket | count | mean_pred | mean_actual |
|---|---|---|---|
| [0.0,0.1) | 18 | 0.0000 | 0.0000 |
| [0.3,0.4) | 34 | 0.3103 | 0.5294 |
| [0.6,0.7) | 7 | 0.6667 | 0.7143 |
| [0.7,0.8) | 24 | 0.7483 | 0.8333 |
| [0.9,1.0) | 1 | 1.0000 | 1.0000 |

## Safety
- artifact staging: staged=None (n/a); not promoted; runtime cannot auto-load.
- Calibration fit on HELD-OUT windows (purged/embargoed); not on model-fit rows.
- Diagnostic-only calibrators are NON_TRADABLE; no PAPER_CANDIDATE; live disabled.
