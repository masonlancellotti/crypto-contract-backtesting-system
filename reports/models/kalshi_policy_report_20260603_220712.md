# Kalshi paper-candidate policy report — KXBTC15M

- policy_enabled: False
- **can_emit_PAPER_CANDIDATE: False**  blockers: ['POLICY_DISABLED', 'MODEL_DIAGNOSTIC_ONLY', 'CALIBRATOR_INVALID']
- gate_windows: 192  rows_evaluated: 24734

## Validity
- model: exists=True trained=True diagnostic_only=True version=microstructure_logistic
- calibrator: exists=True valid=False diagnostic_only=True
- backtest: exists=True valid=True windows=192

## Decisions by state
- {'WATCH': 24734}

## Reason counts
- {'POLICY_DISABLED': 24734}

## Edge distribution
- {'n_with_edge': 0, 'min_net_edge': None, 'max_net_edge': None, 'mean_net_edge': None}

## Source health
- {'underlying_liveness_ok': True, 'underlying_decision_ok': False, 'underlying_reference_source': 'coinbase', 'underlying_fallback_used': False, 'kalshi_liveness_stale': False, 'kalshi_decision_stale': True, 'coinbase_liveness_stale': False, 'coinbase_decision_stale': True, 'binance_liveness_stale': False, 'binance_decision_stale': True, 'underlying_ok': True, 'kalshi_stale': False, 'coinbase_stale': False, 'binance_stale': False, 'deribit_enabled': False}

## Candidate examples
- (none)

## Safety
- PAPER_CANDIDATE requires trained + calibrated + non-diagnostic + backtested model.
- Decisions use calibrated probability + executable ASK EV (never midpoint).
- No live orders; live_submission_allowed=false; hard Up/Down is diagnostic only.
