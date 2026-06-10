# Kalshi SHADOW run — KXBTC15M

- runtime_mode: shadow (forced)  configured_mode: disabled
- manifest_valid: False  status: NO_PROMOTED_PAPER_MODEL
- manifest_path: None
- model: None
- calibrator: None
- rows_evaluated: None  calibration_buckets: None
- decisions_by_state: {}
- shadow_decisions: 0  paper_candidates: 0 (MUST be 0 in shadow)
- blockers: ['NO_PROMOTED_PAPER_MODEL']

## Safety
- SHADOW ONLY: scores + logs; NEVER emits PAPER_CANDIDATE; NEVER paper-fills; NEVER live.
- Artifacts loaded ONLY from the paper-promotion manifest (verified SHA + is_promoted +
  non-diagnostic + calibrated); never newest-by-mtime; staged artifacts never used.
- live_submission_allowed=false.
