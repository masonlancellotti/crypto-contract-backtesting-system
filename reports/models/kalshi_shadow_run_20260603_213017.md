# Kalshi SHADOW run — KXBTC15M

- runtime_mode: shadow (forced)  configured_mode: disabled
- manifest_valid: True  status: OK
- manifest_path: C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\paper_promoted\kalshi_paper_promotion_manifest.json
- model: C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\paper_promoted\paper_model_KXBTC15M_20260603_212839.pkl
- calibrator: C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\paper_promoted\paper_calibrator_KXBTC15M_20260603_212839.pkl
- rows_evaluated: 40  calibration_buckets: 10
- decisions_by_state: {'SHADOW_DECISION': 40}
- shadow_decisions: 40  paper_candidates: 0 (MUST be 0 in shadow)
- blockers: []

## Safety
- SHADOW ONLY: scores + logs; NEVER emits PAPER_CANDIDATE; NEVER paper-fills; NEVER live.
- Artifacts loaded ONLY from the paper-promotion manifest (verified SHA + is_promoted +
  non-diagnostic + calibrated); never newest-by-mtime; staged artifacts never used.
- live_submission_allowed=false.
