# Kalshi edge-policy report — KXBTC15M

- prob_source: microstructure  diagnostic/NON_TRADABLE: **True**  (NON_TRADABLE_DIAGNOSTIC_ONLY)
- gate_windows: 296  promoted: False  live_submission_allowed: False
- config: {"enabled": true, "require_confidence_bounds": true, "min_raw_edge_cents": 5.0, "min_final_edge_cents": 2.0, "base_min_profit_cents": 2.0, "fixed_uncertainty_buffer_cents": 3.0, "min_calibration_bucket_n": 30, "confidence_level": 0.8, "max_prob_interval_width_cents": 12.0}

## Validity
- model tradable/calibrated: **False** — if False, the LIVE policy rejects all
  (UNCALIBRATED_MODEL_REJECTED); the funnel below is STUDY MODE (assumes a calibrated model).

## Candidate survival funnel (study mode)
- candidates: 14136
- survived_raw_edge: 5430
- survived_cost_adjusted: 8046
- survived_uncertainty_adjusted: 2040
- survived_final_edge: 56
- survived_reservation: 373
- survived_depth: 14102
- edge_ok: 52

## Edge distribution (cents)
- raw: {'n': 14136, 'mean': 4.819, 'min': -12.467, 'max': 26.346}
- cost: {'n': 14136, 'mean': 0.276, 'min': -19.871, 'max': 10.648}
- final: {'n': 14136, 'mean': -5.961, 'min': -23.871, 'max': 5.031}

## Rejection reasons
- {"EDGE_BELOW_MIN": 14080, "PRICE_ABOVE_RESERVATION": 13763, "UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN": 12096, "RAW_EDGE_BELOW_MIN": 8706, "COST_ADJUSTED_EDGE_BELOW_MIN": 6090, "REGIME_BUFFER_APPLIED": 2313, "MODEL_DISAGREEMENT_TOO_HIGH": 190, "EDGE_OK": 52, "INSUFFICIENT_DEPTH": 34, "SOURCE_HEALTH_BUFFER_APPLIED": 1}

## EDGE_OK settlement (diagnostic)
- {"edge_ok_trades": 52, "distinct_windows": 11, "net_pnl": 7.086, "hit_rate": 0.8269230769230769}

## Calibration buckets (held-out; Wilson interval)
| range | n | mean_pred | realized | wilson |
|---|---|---|---|---|
| [0.0,0.1) | 5155 | 0.0456 | 0.0555 | [0.0515, 0.0597] |
| [0.1,0.2) | 1545 | 0.146 | 0.2524 | [0.2385, 0.2668] |
| [0.2,0.3) | 982 | 0.2456 | 0.3228 | [0.304, 0.3422] |
| [0.3,0.4) | 559 | 0.3458 | 0.4669 | [0.44, 0.494] |
| [0.4,0.5) | 503 | 0.4499 | 0.6461 | [0.6184, 0.6729] |
| [0.5,0.6) | 454 | 0.5517 | 0.6233 | [0.5938, 0.652] |
| [0.6,0.7) | 542 | 0.6522 | 0.7214 | [0.6961, 0.7454] |
| [0.7,0.8) | 799 | 0.7534 | 0.8273 | [0.8095, 0.8437] |
| [0.8,0.9) | 1184 | 0.8517 | 0.9079 | [0.8966, 0.9181] |
| [0.9,1.0) | 2413 | 0.9442 | 0.9979 | [0.9964, 0.9988] |

## Recommended conservative settings (NOT promoted; manual review)
- {"min_raw_edge_cents": 5, "min_final_edge_cents": 2, "base_min_profit_cents": 2, "fixed_uncertainty_buffer_cents": 3, "min_calibration_bucket_n": 30, "confidence_level": 0.8, "max_prob_interval_width_cents": 12}
- rationale: Conservative defaults: require a calibrated+backtested model, a >=5c raw edge, and a >=2c final edge AFTER fees + model/calibration/regime/overtrading buffers. Reservation price uses the conservative probability bound, not the point estimate.

## Safety
- RESEARCH/REPORTING ONLY: no orders, no PAPER_CANDIDATE, no live trading.
- No policy/model promoted; recommendations require manual review + paper validation.
- Edge is NOT model_prob - price: it is conservative-bound edge minus fees + uncertainty
  + regime + overtrading + minimum-profit buffers; reservation uses the conservative bound.
- Uncalibrated/diagnostic model => the live policy rejects ALL candidates.
