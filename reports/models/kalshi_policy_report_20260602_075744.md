# Kalshi paper-candidate policy report — KXBTC15M

- policy_enabled: True
- **can_emit_PAPER_CANDIDATE: False**  blockers: ['MODEL_DIAGNOSTIC_ONLY', 'CALIBRATOR_INVALID', 'BACKTEST_INSUFFICIENT']
- gate_windows: 48  rows_evaluated: 200

## Validity
- model: exists=True trained=True diagnostic_only=True version=microstructure_logistic
- calibrator: exists=True valid=False diagnostic_only=True
- backtest: exists=True valid=False windows=48

## Decisions by state
- {'REJECTED': 200}

## Reason counts
- {'MODEL_DIAGNOSTIC_ONLY': 200, 'CALIBRATOR_INVALID': 200, 'BACKTEST_INSUFFICIENT': 200}

## Edge distribution
- {'n_with_edge': 0, 'min_net_edge': None, 'max_net_edge': None, 'mean_net_edge': None}

## Source health
- {'underlying_ok': True, 'kalshi_stale': False, 'coinbase_stale': False, 'binance_stale': False, 'deribit_enabled': False}

## Candidate examples
- (none)

## Safety
- PAPER_CANDIDATE requires trained + calibrated + non-diagnostic + backtested model.
- Decisions use calibrated probability + executable ASK EV (never midpoint).
- No live orders; live_submission_allowed=false; hard Up/Down is diagnostic only.
