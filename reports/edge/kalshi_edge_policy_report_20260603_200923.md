# Kalshi edge-policy report — KXBTC15M

- prob_source: microstructure  diagnostic/NON_TRADABLE: **True**  (NON_TRADABLE_DIAGNOSTIC_ONLY)
- gate_windows: 187  promoted: False  live_submission_allowed: False
- config: {"enabled": true, "require_confidence_bounds": true, "min_raw_edge_cents": 5.0, "min_final_edge_cents": 2.0, "base_min_profit_cents": 2.0, "fixed_uncertainty_buffer_cents": 3.0, "min_calibration_bucket_n": 30, "confidence_level": 0.8, "max_prob_interval_width_cents": 12.0}

## Validity
- model tradable/calibrated: **False** — if False, the LIVE policy rejects all
  (UNCALIBRATED_MODEL_REJECTED); the funnel below is STUDY MODE (assumes a calibrated model).

## Candidate survival funnel (study mode)
- candidates: 7469
- survived_raw_edge: 3537
- survived_cost_adjusted: 4746
- survived_uncertainty_adjusted: 647
- survived_final_edge: 11
- survived_reservation: 61
- survived_depth: 7441
- edge_ok: 11

## Edge distribution (cents)
- raw: {'n': 7469, 'mean': 5.942, 'min': -9.956, 'max': 29.451}
- cost: {'n': 7469, 'mean': 0.748, 'min': -24.598, 'max': 9.97}
- final: {'n': 7469, 'mean': -6.915, 'min': -32.585, 'max': 4.739}

## Rejection reasons
- {"EDGE_BELOW_MIN": 7458, "PRICE_ABOVE_RESERVATION": 7408, "UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN": 6822, "RAW_EDGE_BELOW_MIN": 3932, "COST_ADJUSTED_EDGE_BELOW_MIN": 2723, "MODEL_DISAGREEMENT_TOO_HIGH": 239, "REGIME_BUFFER_APPLIED": 28, "INSUFFICIENT_DEPTH": 28, "EDGE_OK": 11, "SOURCE_HEALTH_BUFFER_APPLIED": 6}

## EDGE_OK settlement (diagnostic)
- {"edge_ok_trades": 11, "distinct_windows": 1, "net_pnl": 9.959, "hit_rate": 1.0}

## Calibration buckets (held-out; Wilson interval)
| range | n | mean_pred | realized | wilson |
|---|---|---|---|---|
| [0.0,0.1) | 2197 | 0.0507 | 0.102 | [0.094, 0.1105] |
| [0.1,0.2) | 788 | 0.1434 | 0.302 | [0.2815, 0.3234] |
| [0.2,0.3) | 562 | 0.2497 | 0.3648 | [0.3392, 0.3911] |
| [0.3,0.4) | 501 | 0.3501 | 0.4012 | [0.3735, 0.4295] |
| [0.4,0.5) | 427 | 0.4474 | 0.5504 | [0.5194, 0.581] |
| [0.5,0.6) | 408 | 0.5477 | 0.6225 | [0.5914, 0.6528] |
| [0.6,0.7) | 450 | 0.6504 | 0.6311 | [0.6015, 0.6597] |
| [0.7,0.8) | 435 | 0.7479 | 0.6828 | [0.6535, 0.7106] |
| [0.8,0.9) | 571 | 0.8528 | 0.8196 | [0.7981, 0.8393] |
| [0.9,1.0) | 1130 | 0.9471 | 0.9752 | [0.9686, 0.9805] |

## Recommended conservative settings (NOT promoted; manual review)
- {"min_raw_edge_cents": 5, "min_final_edge_cents": 2, "base_min_profit_cents": 2, "fixed_uncertainty_buffer_cents": 3, "min_calibration_bucket_n": 30, "confidence_level": 0.8, "max_prob_interval_width_cents": 12}
- rationale: Conservative defaults: require a calibrated+backtested model, a >=5c raw edge, and a >=2c final edge AFTER fees + model/calibration/regime/overtrading buffers. Reservation price uses the conservative probability bound, not the point estimate.

## Safety
- RESEARCH/REPORTING ONLY: no orders, no PAPER_CANDIDATE, no live trading.
- No policy/model promoted; recommendations require manual review + paper validation.
- Edge is NOT model_prob - price: it is conservative-bound edge minus fees + uncertainty
  + regime + overtrading + minimum-profit buffers; reservation uses the conservative bound.
- Uncalibrated/diagnostic model => the live policy rejects ALL candidates.
