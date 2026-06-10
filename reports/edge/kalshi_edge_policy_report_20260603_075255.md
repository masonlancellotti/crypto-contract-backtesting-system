# Kalshi edge-policy report — KXBTC15M

- prob_source: microstructure  diagnostic/NON_TRADABLE: **True**  (NON_TRADABLE_DIAGNOSTIC_ONLY)
- gate_windows: 144  promoted: False  live_submission_allowed: False
- config: {"enabled": true, "require_confidence_bounds": true, "min_raw_edge_cents": 5.0, "min_final_edge_cents": 2.0, "base_min_profit_cents": 2.0, "fixed_uncertainty_buffer_cents": 3.0, "min_calibration_bucket_n": 30, "confidence_level": 0.8, "max_prob_interval_width_cents": 12.0}

## Validity
- model tradable/calibrated: **False** — if False, the LIVE policy rejects all
  (UNCALIBRATED_MODEL_REJECTED); the funnel below is STUDY MODE (assumes a calibrated model).

## Candidate survival funnel (study mode)
- candidates: 5508
- survived_raw_edge: 2547
- survived_cost_adjusted: 3409
- survived_uncertainty_adjusted: 660
- survived_final_edge: 59
- survived_reservation: 131
- survived_depth: 5497
- edge_ok: 17

## Edge distribution (cents)
- raw: {'n': 5508, 'mean': 6.709, 'min': -9.197, 'max': 47.066}
- cost: {'n': 5508, 'mean': 1.263, 'min': -15.569, 'max': 19.105}
- final: {'n': 5508, 'mean': -5.904, 'min': -18.405, 'max': 11.087}

## Rejection reasons
- {"EDGE_BELOW_MIN": 5449, "PRICE_ABOVE_RESERVATION": 5377, "UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN": 4848, "RAW_EDGE_BELOW_MIN": 2961, "COST_ADJUSTED_EDGE_BELOW_MIN": 2099, "MODEL_DISAGREEMENT_TOO_HIGH": 487, "EDGE_OK": 17, "REGIME_BUFFER_APPLIED": 11, "INSUFFICIENT_DEPTH": 11, "SOURCE_HEALTH_BUFFER_APPLIED": 7}

## EDGE_OK settlement (diagnostic)
- {"edge_ok_trades": 17, "distinct_windows": 3, "net_pnl": -2.093, "hit_rate": 0.0}

## Calibration buckets (held-out; Wilson interval)
| range | n | mean_pred | realized | wilson |
|---|---|---|---|---|
| [0.0,0.1) | 1702 | 0.0427 | 0.0934 | [0.0848, 0.1029] |
| [0.1,0.2) | 509 | 0.145 | 0.2908 | [0.2657, 0.3172] |
| [0.2,0.3) | 376 | 0.2484 | 0.3431 | [0.3125, 0.3751] |
| [0.3,0.4) | 278 | 0.3508 | 0.4209 | [0.3835, 0.4592] |
| [0.4,0.5) | 288 | 0.4485 | 0.5174 | [0.4796, 0.5549] |
| [0.5,0.6) | 301 | 0.5499 | 0.6412 | [0.6051, 0.6758] |
| [0.6,0.7) | 330 | 0.6497 | 0.6576 | [0.6234, 0.6902] |
| [0.7,0.8) | 299 | 0.7519 | 0.7191 | [0.6846, 0.7511] |
| [0.8,0.9) | 394 | 0.8553 | 0.7665 | [0.7381, 0.7927] |
| [0.9,1.0) | 1031 | 0.9531 | 0.9525 | [0.9432, 0.9603] |

## Recommended conservative settings (NOT promoted; manual review)
- {"min_raw_edge_cents": 5, "min_final_edge_cents": 2, "base_min_profit_cents": 2, "fixed_uncertainty_buffer_cents": 3, "min_calibration_bucket_n": 30, "confidence_level": 0.8, "max_prob_interval_width_cents": 12}
- rationale: Conservative defaults: require a calibrated+backtested model, a >=5c raw edge, and a >=2c final edge AFTER fees + model/calibration/regime/overtrading buffers. Reservation price uses the conservative probability bound, not the point estimate.

## Safety
- RESEARCH/REPORTING ONLY: no orders, no PAPER_CANDIDATE, no live trading.
- No policy/model promoted; recommendations require manual review + paper validation.
- Edge is NOT model_prob - price: it is conservative-bound edge minus fees + uncertainty
  + regime + overtrading + minimum-profit buffers; reservation uses the conservative bound.
- Uncalibrated/diagnostic model => the live policy rejects ALL candidates.
