"""Configuration loading and safety resolution.

Precedence (highest wins):
    1. environment variables (incl. values loaded from `.env`)
    2. mode-specific YAML (e.g. config/paper.yaml)
    3. config/default.yaml
    4. built-in safe defaults

Imports cleanly with no third-party deps; PyYAML and python-dotenv are optional
and imported lazily. Missing them degrades to env + built-in defaults, never an
import error. No secret is ever required merely to load config.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    v = raw.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return default


def _env_float(name: str) -> Optional[float]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _env_int(name: str) -> Optional[int]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def load_dotenv_if_present(path: str | os.PathLike[str] | None = None) -> None:
    """Load a `.env` file into os.environ if python-dotenv is available.

    Silent no-op if the library or file is missing. Existing env vars win.
    """
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    target = Path(path) if path else REPO_ROOT / ".env"
    if target.exists():
        load_dotenv(target, override=False)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore
    except Exception:
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# --------------------------------------------------------------------------- #
# Config dataclasses
# --------------------------------------------------------------------------- #
@dataclass
class RiskLimits:
    max_order_size: Optional[float] = None
    max_position_per_contract: Optional[float] = None
    max_daily_loss: Optional[float] = None
    max_open_risk: Optional[float] = None
    max_trades_per_hour: Optional[int] = None
    max_quote_age_ms: int = 1500
    max_clock_skew_ms: int = 2000
    max_feed_gap_ms: int = 5000
    reject_crossed_book: bool = True
    require_settlement_metadata: bool = True
    max_calibration_age_hours: float = 24.0


@dataclass
class ExecutionConfig:
    assume_midpoint_fills: bool = False  # NEVER true
    taker_fee_bps: float = 0.0
    min_net_edge_cents: float = 2.0
    slippage_model: str = "depth_walk"


@dataclass
class NotificationConfig:
    provider: str = "auto"  # auto | pushover | noop
    event_prefix: str = "btc5m"
    # Pushover (secrets come from env only; never hard-coded)
    pushover_enabled: bool = False
    pushover_app_token: Optional[str] = None
    pushover_user_key: Optional[str] = None
    pushover_device: Optional[str] = None
    pushover_priority: int = 0
    pushover_sound: Optional[str] = None
    pushover_api_url: str = "https://api.pushover.net/1/messages.json"
    # Latency-safe async queue. The hot/decision path enqueues an event in-memory
    # and returns immediately; a background worker performs the actual send. These
    # defaults keep notifications best-effort and Noop-safe.
    async_enabled: bool = True
    queue_maxsize: int = 500
    send_timeout_ms: int = 750               # per-send network timeout (250-1000ms)
    drop_low_priority_when_full: bool = True
    coalesce_watch: bool = True
    hotpath_blocking_forbidden: bool = True  # guard: hot path must enqueue, never send

    @property
    def pushover_configured(self) -> bool:
        """True only when explicitly enabled AND both required creds present."""
        return bool(
            self.pushover_enabled and self.pushover_app_token and self.pushover_user_key
        )


@dataclass
class PolymarketCreds:
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    api_passphrase: Optional[str] = None
    funder_address: Optional[str] = None
    wallet_address: Optional[str] = None

    @property
    def complete(self) -> bool:
        return all(
            [
                self.api_key,
                self.api_secret,
                self.api_passphrase,
                self.funder_address,
                self.wallet_address,
            ]
        )


@dataclass
class KalshiConfig:
    """Kalshi venue config. Public market data needs NO auth; key_id +
    private_key_path are only needed for authenticated WS / account / live.

    Fee assumptions live here and are stamped onto ledgers/decisions. They are
    ASSUMED (not OFFICIAL) until verified against Kalshi's published schedule.
    """

    env: str = "prod"
    api_base: str = "https://external-api.kalshi.com/trade-api/v2"
    ws_url: str = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
    series_ticker: str = "KXBTC15M"
    key_id: Optional[str] = None
    private_key_path: Optional[str] = None
    private_key_passphrase: Optional[str] = None
    # Fee model assumptions (see venues/kalshi/fees.py).
    fee_status: str = "ASSUMED"          # OFFICIAL | ASSUMED | UNKNOWN
    fee_rate: float = 0.07               # taker-fee coefficient
    fee_formula: str = "round_up_cent(rate * contracts * price * (1 - price))"

    @property
    def auth_configured(self) -> bool:
        """True only when BOTH a key id and a private-key path are set."""
        return bool(self.key_id and self.private_key_path)


@dataclass
class DeribitConfig:
    """Optional auxiliary Deribit volatility/options source.

    DISABLED by default and NOT required for the Kalshi MVP. Public REST reads
    (DVOL, index, historical vol, option book summary) need NO credentials;
    client_id/secret are only for private endpoints we do not use.
    """

    enabled: bool = False
    api_url: str = "https://www.deribit.com/api/v2"
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    # Deribit is slower-moving context: poll it infrequently and treat it as
    # stale on a much looser threshold than the per-second underlying feeds.
    poll_interval_seconds: int = 30
    stale_threshold_seconds: int = 180
    # Whether Deribit columns may enter the model CANDIDATE feature group. This is
    # SEPARATE from ``enabled`` (which controls live collection / source usage): a
    # disabled Deribit whose historical columns linger in old feature rows must NOT
    # silently feed the model. Defaults False.
    include_in_model_features: bool = False
    # Escape hatch — allow Deribit columns from historical rows to be selected for
    # the model even while disabled. Off by default so disabled never means silent.
    allow_historical_features_when_disabled: bool = False
    # Recording toggles for the optional Deribit raw/normalized JSONL streams.
    record_raw: bool = True
    record_normalized: bool = True

    @property
    def select_for_model_features(self) -> bool:
        """True only when Deribit columns may enter the model candidate feature group.

        Requires ``include_in_model_features`` AND either an enabled live source or
        an explicit opt-in to use historical rows while disabled. A disabled Deribit
        with leftover historical columns is therefore NEVER silently selected.
        """
        if not self.include_in_model_features:
            return False
        if self.enabled:
            return True
        return self.allow_historical_features_when_disabled


@dataclass
class LowLatencyConfig:
    """5-minute-grade low-latency hot-path settings (SAFE by default).

    The hot path is disabled unless explicitly enabled, paper-only, and can never
    submit live orders. WebSocket is off unless enabled AND Kalshi auth is present;
    REST polling is the fallback. Horizon fields make 15m-vs-future-5m behavior
    config-driven (same architecture, different knobs).
    """

    enabled: bool = False
    use_websocket: bool = False
    rest_fallback_enabled: bool = True
    hotpath_score_interval_ms: int = 250
    max_book_age_ms: int = 1000
    max_underlying_age_ms: int = 2000
    max_deribit_age_ms: int = 180_000
    profile: bool = False
    log_every_n: int = 100
    paper_only: bool = True
    order_planning_enabled: bool = False
    allowed_time_in_force: tuple[str, ...] = ("fill_or_kill", "immediate_or_cancel")
    # Horizon (config-driven: KXBTC15M now, KXBTC5M-style later — same code path).
    market_duration_seconds: int = 900
    min_seconds_to_close: int = 10
    max_seconds_to_close: int = 900
    feature_lookbacks_seconds: tuple[int, ...] = (5, 15, 30, 60, 180)
    min_depth: float = 1.0
    min_net_edge_cents: float = 2.0
    uncertainty_buffer_cents: float = 0.0

    @property
    def live_submission_allowed(self) -> bool:
        """The hot path NEVER submits live orders, regardless of settings."""
        return False


@dataclass
class BacktestConfig:
    """Calibration + executable-backtest settings (SAFE/conservative defaults).

    The backtest is RESEARCH ONLY: it simulates executable YES/NO entries (ask
    prices, never midpoint) net of fees/depth/staleness and produces evidence — it
    never trades and never emits PAPER_CANDIDATE. Real calibration/backtest are
    gated on DISTINCT feature-backed official 15m windows; ``allow_diagnostic``
    (or per-command --diagnostic-only) permits below-gate runs that are stamped
    NON_TRADABLE_DIAGNOSTIC_ONLY.
    """

    min_windows: int = 60                  # backtest diagnostic gate
    train_min_windows: int = 150
    calibration_min_windows: int = 150
    default_size: float = 1.0
    min_net_edge_cents: float = 2.0
    max_book_age_ms: int = 1000
    max_underlying_age_ms: int = 2000
    min_seconds_to_close: int = 5
    max_seconds_to_close: int = 900
    max_spread: float = 1.0                # in price units (1.0 == no spread cap)
    min_depth: float = 1.0
    uncertainty_buffer_cents: float = 0.0
    allow_diagnostic: bool = False
    use_deribit_filters: bool = False


@dataclass
class PaperPolicyConfig:
    """Paper-candidate policy gates (CONSERVATIVE/disabled by default).

    The policy decides WATCH / MANUAL_REVIEW / REJECTED / PAPER_CANDIDATE. It NEVER
    trades and NEVER reaches live. PAPER_CANDIDATE is only possible when the policy
    is enabled AND a trained, calibrated, non-diagnostic, sufficiently-backtested
    model passes every executable-EV / freshness / liquidity / time / risk gate.
    """

    enabled: bool = False
    require_trained_model: bool = True
    require_calibrated_model: bool = True
    require_backtest_evidence: bool = True
    require_non_diagnostic_model: bool = True
    # ----- paper promotion + runtime gates (paper-only; never live) -----
    # The runtime loads ONLY an explicit paper-promotion manifest (never newest-by-mtime
    # or staged artifacts) when these are set. PAPER_CANDIDATE also requires the
    # confidence-aware edge policy + a frequency report to exist.
    promotion_required: bool = True
    require_promoted_paper_model: bool = True
    require_edge_policy: bool = True
    require_frequency_report: bool = True
    # conservative trade-rate caps (Part G)
    max_daily_trades: int = 10
    entry_cooldown_seconds: int = 30
    min_calibration_windows: int = 150
    min_backtest_windows: int = 60
    min_net_edge_cents: float = 2.0
    min_raw_edge_cents: float = 3.0
    uncertainty_buffer_cents: float = 1.0
    slippage_buffer_cents: float = 0.0
    max_yes_price_cents: float = 95.0
    max_no_price_cents: float = 95.0
    max_book_age_ms: int = 1000
    max_underlying_age_ms: int = 2000
    max_deribit_age_ms: int = 180_000
    require_deribit_fresh: bool = False
    max_spread_cents: float = 10.0
    min_top_depth_contracts: float = 1.0
    min_seconds_to_close: int = 5
    max_seconds_to_close: int = 900
    max_trades_per_window: int = 1
    max_open_positions: int = 1
    max_position_per_contract: float = 1.0
    paper_default_size: float = 1.0
    allow_diagnostic_paper: bool = False
    notify_paper_candidates: bool = True

    @property
    def live_submission_allowed(self) -> bool:
        """The policy can NEVER submit a live order, regardless of settings."""
        return False


@dataclass
class LockConfig:
    """Post-entry lock-profit settings (paper-only; disabled by default; never live).

    This is POSITION MANAGEMENT after a paper directional entry — NOT a flat-position
    arb scanner. It only ever evaluates buying the OPPOSITE leg of an EXISTING paper
    position to lock guaranteed profit after fees. It never opens directional
    positions, never scans flat markets, and never submits a live order.
    """

    enabled: bool = False
    paper_only: bool = True
    min_profit_cents: float = 2.0
    hard_profit_cents: float = 5.0
    allow_partial: bool = False
    default_mode: str = "fok"            # fok | ioc
    max_book_age_ms: int = 1000
    max_underlying_age_ms: int = 2000
    min_depth_contracts: float = 1.0
    min_seconds_to_close: int = 3
    ride_min_edge_cents: float = 3.0
    force_when_model_edge_below_cents: float = 1.0
    slippage_buffer_cents: float = 0.0
    require_underlying_fresh: bool = False
    notify: bool = True

    @property
    def live_submission_allowed(self) -> bool:
        """Lock logic can NEVER submit a live order, regardless of settings."""
        return False


@dataclass
class LifecycleConfig:
    """Post-entry position lifecycle manager (paper-only; disabled by default; never live).

    Orchestrates same-leg exit value vs opposite-leg lock value vs continue/ride EV
    for an EXISTING paper position. It never opens positions, never scans flat
    markets, and never submits a live order. Thresholds are in cents.
    """

    enabled: bool = False
    paper_only: bool = True
    min_sell_profit_cents: float = 2.0
    hard_sell_profit_cents: float = 5.0
    min_lock_profit_cents: float = 2.0
    hard_lock_profit_cents: float = 5.0
    ride_min_edge_cents: float = 3.0
    force_exit_when_model_edge_below_cents: float = 0.0
    force_lock_when_model_edge_below_cents: float = 1.0
    allow_partial_exit: bool = False
    allow_partial_lock: bool = False
    default_tif: str = "fill_or_kill"
    max_book_age_ms: int = 1000
    max_underlying_age_ms: int = 2000
    min_depth_contracts: float = 1.0
    min_seconds_to_close: int = 3
    max_spread_cents: float = 10.0
    notify: bool = True

    @property
    def live_submission_allowed(self) -> bool:
        """Lifecycle logic can NEVER submit a live order, regardless of settings."""
        return False


@dataclass
class FrequencyConfig:
    """Trade-frequency frontier / overtrading ANALYSIS (research/reporting only).

    Never trades, never promotes a policy, never enables live. ``do_not_promote``
    is advisory documentation — the module has no promotion path.
    """

    enabled: bool = True
    default_max_scenarios: int = 250
    min_net_edge_grid_cents: tuple = (1.0, 2.0, 3.0, 5.0, 7.0, 10.0)
    max_trades_per_window_grid: tuple = (1, 2, 3, 5)
    cooldown_grid_seconds: tuple = (0, 5, 15, 30, 60)
    min_seconds_to_close_grid: tuple = (5, 15, 30, 60, 120)
    report_top_n: tuple = (5, 10, 20, 50, 100)
    do_not_promote: bool = True


@dataclass
class EdgePolicyConfig:
    """Confidence-aware edge threshold / reservation-price policy (paper-only; never live).

    Conservative by default: no PAPER_CANDIDATE unless the model is trained +
    calibrated + backtested AND the conservative edge survives all buffers. Never
    promotes a policy. Thresholds/buffers in cents.
    """

    enabled: bool = True
    require_confidence_bounds: bool = True
    min_raw_edge_cents: float = 5.0
    min_final_edge_cents: float = 2.0
    base_min_profit_cents: float = 2.0
    fixed_uncertainty_buffer_cents: float = 3.0
    min_calibration_bucket_n: int = 30
    confidence_level: float = 0.80
    max_prob_interval_width_cents: float = 12.0
    use_calibration_buckets: bool = True
    use_window_bootstrap: bool = False
    bootstrap_samples: int = 500
    use_ensemble_disagreement: bool = True
    max_model_disagreement_cents: float = 10.0
    stale_quote_buffer_cents: float = 1.0
    source_stale_buffer_cents: float = 2.0
    high_vol_regime_buffer_cents: float = 2.0
    thin_book_buffer_cents: float = 2.0
    overtrading_buffer_cents: float = 1.0
    min_book_depth: float = 1.0
    max_spread_cents: float = 10.0
    max_book_age_ms: int = 1000
    max_underlying_age_ms: int = 2000
    report_breakdown: bool = True
    # Reliability unit for REPORTING (row | window | both). Rows within a 15m window are
    # not independent, so row-based Wilson intervals are fake-tight; the distinct-window
    # unit is the honest one. This controls reporting only — the production edge policy is
    # unchanged in this build. Window-based reliability tends to WIDEN (never loosen) the
    # buffer, so it can only make the gate more conservative.
    reliability_unit: str = "both"


@dataclass
class LiveReadinessConfig:
    """Live-readiness scaffolding (SAFE/locked by default; NEVER submits).

    Lets the live path be validated/inspected in dry-run only. Live submission is
    impossible here: ``live_submission_allowed`` is always False and every default
    keeps the plane in the hangar (paper mode, kill switch on, dry-run only, submit
    disabled, manual confirmation required, no market orders, tiny limits).
    """

    enabled: bool = False                 # readiness scaffolding active (still no submit)
    dry_run_only: bool = True
    submit_enabled: bool = False
    allow_private_reads: bool = False
    max_live_order_size: float = 1.0
    max_live_notional: float = 10.0
    max_live_daily_loss: float = 10.0
    max_live_open_exposure: float = 10.0
    require_approved_model: bool = True
    require_valid_calibrator: bool = True
    require_valid_backtest: bool = True
    require_paper_evidence: bool = True
    require_source_health: bool = True
    require_fresh_book: bool = True
    require_limit_order: bool = True
    require_fok_or_ioc: bool = True
    allow_market_orders: bool = False
    precheck_timeout_ms: int = 1000

    @property
    def live_submission_allowed(self) -> bool:
        return False


@dataclass
class FreshnessConfig:
    """Source-freshness thresholds — LIVENESS vs DECISION freshness are SEPARATE.

    LIVENESS answers "is the collector generally alive?" (loose, ~60s). DECISION
    freshness answers "is this data fresh enough to SCORE / emit PAPER_CANDIDATE?"
    (strict, ~1s book / ~5s underlying). A collector can be alive while its data is
    too stale to trade on. These two must never be conflated. All values in ms.
    """

    # ----- Kalshi executable book -----
    kalshi_book_liveness_ms: int = 60_000
    kalshi_book_decision_max_age_ms: int = 1_000
    # ----- Coinbase BTC spot (PRIMARY underlying reference) -----
    coinbase_liveness_ms: int = 60_000
    coinbase_decision_max_age_ms: int = 5_000
    # ----- Binance perp (basis/microstructure + spot fallback) -----
    binance_liveness_ms: int = 60_000
    binance_decision_max_age_ms: int = 5_000
    # ----- Deribit (optional vol/regime context; loose) -----
    deribit_liveness_ms: int = 180_000
    deribit_decision_max_age_ms: int = 180_000
    # ----- underlying group / fallback policy -----
    underlying_require_one_fresh: bool = True
    underlying_primary: str = "coinbase"
    underlying_fallback: str = "binance"
    underlying_allow_binance_fallback: bool = True
    underlying_require_primary_for_entry: bool = False
    underlying_reject_if_both_stale: bool = True
    # ----- paper-candidate freshness gates (NEVER let stale data trade) -----
    reject_paper_if_book_stale: bool = True
    reject_paper_if_underlying_stale: bool = True
    reject_paper_if_feature_row_stale: bool = True
    feature_row_max_age_ms: int = 1_000


@dataclass
class PaperExperimentConfig:
    """Controlled PAPER experiment settings (shadow first, paper only if preflight passes).

    NEVER live. ``allow_live`` is documentation-only and is never honored. Defaults are
    safe: experiment disabled, mode shadow, promoted model required, diagnostic rejected,
    strict source freshness, conservative trade frequency, and explicit abort criteria.
    """

    enabled: bool = False
    mode: str = "shadow"                       # disabled | shadow | paper (never live)
    name: str = ""
    max_duration_minutes: int = 360
    max_daily_trades: int = 10
    max_trades_per_window: int = 1
    max_open_positions: int = 1
    default_size: float = 1.0
    # conservative edge thresholds (cents)
    min_net_edge_cents: float = 5.0
    min_final_edge_cents: float = 2.0
    min_raw_edge_cents: float = 5.0
    cooldown_seconds: int = 30
    min_seconds_to_close: int = 10
    max_seconds_to_close: int = 900
    # decision-freshness windows (ms)
    max_book_age_ms: int = 1000
    max_underlying_age_ms: int = 5000
    max_deribit_age_ms: int = 180000
    # required preconditions
    require_promoted_model: bool = True
    require_calibrator: bool = True
    require_edge_policy: bool = True
    require_source_freshness: bool = True
    require_backtest_report: bool = True
    allow_diagnostic: bool = False
    allow_live: bool = False                   # documentation-only; NEVER honored
    # abort criteria
    abort_on_source_stale: bool = True
    abort_on_model_error: bool = True
    abort_on_policy_error: bool = True
    abort_on_unexpected_live_enabled: bool = True
    max_consecutive_rejections: int = 100
    max_drawdown_cents: float = 100.0
    max_daily_paper_loss_cents: float = 100.0

    @property
    def live_submission_allowed(self) -> bool:
        """Experiments can NEVER submit live orders, regardless of settings."""
        return False


@dataclass
class AppConfig:
    # Safety / mode
    trading_mode: str = "paper"
    live_trading_enabled: bool = False
    require_manual_confirmation: bool = True
    kill_switch_enabled: bool = True

    # Venue posture: Kalshi is the PRIMARY venue; Polymarket is parked/dormant.
    primary_venue: str = "kalshi"
    polymarket_dormant: bool = True

    # Model runtime mode: disabled | shadow | paper (never "live" here). Controls how
    # the paper runtime loads/uses a PROMOTED paper model. Default disabled = no
    # model-driven paper candidates; shadow = score/log only (no fills); paper =
    # PAPER_CANDIDATE + paper fills allowed if every gate passes. live_submission_allowed
    # is always False regardless of mode.
    model_runtime_mode: str = "disabled"

    # Localization
    timezone: str = "Europe/Dublin"
    eod_summary_time: str = "00:00"

    # Sub-configs
    risk: RiskLimits = field(default_factory=RiskLimits)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    polymarket: PolymarketCreds = field(default_factory=PolymarketCreds)
    kalshi: KalshiConfig = field(default_factory=KalshiConfig)
    deribit: DeribitConfig = field(default_factory=DeribitConfig)
    low_latency: LowLatencyConfig = field(default_factory=LowLatencyConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    paper_policy: PaperPolicyConfig = field(default_factory=PaperPolicyConfig)
    lock: LockConfig = field(default_factory=LockConfig)
    lifecycle: LifecycleConfig = field(default_factory=LifecycleConfig)
    frequency: FrequencyConfig = field(default_factory=FrequencyConfig)
    edge_policy: EdgePolicyConfig = field(default_factory=EdgePolicyConfig)
    live_readiness: LiveReadinessConfig = field(default_factory=LiveReadinessConfig)
    freshness: FreshnessConfig = field(default_factory=FreshnessConfig)
    paper_experiment: PaperExperimentConfig = field(default_factory=PaperExperimentConfig)

    # Paper
    paper_starting_bankroll: float = 1000.0

    # Paths / logging
    data_dir: str = "./data"
    reports_dir: str = "./reports"
    log_level: str = "INFO"

    # Raw merged source/section dicts (for adapters to read endpoint config)
    sources: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    # ----- Safety helpers ---------------------------------------------------
    @property
    def is_live_mode(self) -> bool:
        return self.trading_mode.lower() == "live"

    def live_blockers(self) -> list[str]:
        """Reasons live trading is NOT permitted. Empty list => permitted."""
        blockers: list[str] = []
        if not self.is_live_mode:
            blockers.append(f"TRADING_MODE is '{self.trading_mode}', not 'live'")
        if not self.live_trading_enabled:
            blockers.append("LIVE_TRADING_ENABLED is false")
        if self.kill_switch_enabled:
            blockers.append("KILL_SWITCH_ENABLED is true (kill switch active)")
        # Credential gate is for the PRIMARY venue (Kalshi). Polymarket is dormant.
        if self.primary_venue == "kalshi":
            if not self.kalshi.auth_configured:
                blockers.append("Kalshi auth not configured (KALSHI_KEY_ID / KALSHI_PRIVATE_KEY_PATH)")
        elif not self.polymarket.complete:
            blockers.append("Polymarket credentials incomplete")
        if not self._risk_limits_set():
            blockers.append("Required risk limits are not all set")
        return blockers

    def _risk_limits_set(self) -> bool:
        r = self.risk
        return all(
            v is not None
            for v in (
                r.max_order_size,
                r.max_position_per_contract,
                r.max_daily_loss,
                r.max_open_risk,
                r.max_trades_per_hour,
            )
        )

    @property
    def live_permitted(self) -> bool:
        return not self.live_blockers()

    def data_path(self) -> Path:
        return (REPO_ROOT / self.data_dir).resolve() if self.data_dir.startswith(".") else Path(
            self.data_dir
        )

    def reports_path(self) -> Path:
        return (REPO_ROOT / self.reports_dir).resolve() if self.reports_dir.startswith(
            "."
        ) else Path(self.reports_dir)


# --------------------------------------------------------------------------- #
# Loader
# --------------------------------------------------------------------------- #
def load_config(mode: Optional[str] = None, *, load_env: bool = True) -> AppConfig:
    """Build an :class:`AppConfig` from YAML + environment.

    `mode` selects an optional `config/<mode>.yaml` overlay (e.g. "paper").
    If not given, falls back to TRADING_MODE env or the default config value.
    """
    if load_env:
        load_dotenv_if_present()

    merged = _load_yaml(CONFIG_DIR / "default.yaml")

    selected_mode = mode or os.environ.get("TRADING_MODE")
    if selected_mode:
        overlay = _load_yaml(CONFIG_DIR / f"{selected_mode}.yaml")
        merged = _deep_merge(merged, overlay)

    cfg = _from_dict(merged)
    _apply_env_overrides(cfg)
    return cfg


def _from_dict(d: dict[str, Any]) -> AppConfig:
    trading = d.get("trading", {})
    loc = d.get("localization", {})
    risk = d.get("risk", {})
    execu = d.get("execution", {})
    paper = d.get("paper", {})
    data = d.get("data", {})
    notif = d.get("notifications", {})
    logging_ = d.get("logging", {})

    cfg = AppConfig(
        trading_mode=str(trading.get("mode", "paper")),
        live_trading_enabled=bool(trading.get("live_trading_enabled", False)),
        require_manual_confirmation=bool(trading.get("require_manual_confirmation", True)),
        kill_switch_enabled=bool(trading.get("kill_switch_enabled", True)),
        timezone=str(loc.get("timezone", "Europe/Dublin")),
        eod_summary_time=str(loc.get("eod_summary_time", "00:00")),
        risk=RiskLimits(**{k: risk.get(k) for k in _field_names(RiskLimits) if k in risk}),
        execution=ExecutionConfig(
            **{k: execu.get(k) for k in _field_names(ExecutionConfig) if k in execu}
        ),
        notifications=NotificationConfig(
            provider=str(notif.get("provider", "auto")),
            event_prefix=str(notif.get("event_prefix", "btc5m")),
            pushover_api_url=str(
                notif.get("pushover_api_url", "https://api.pushover.net/1/messages.json")
            ),
        ),
        paper_starting_bankroll=float(paper.get("starting_bankroll", 1000.0)),
        data_dir=str(data.get("data_dir", "./data")),
        reports_dir=str(data.get("reports_dir", "./reports")),
        log_level=str(logging_.get("level", "INFO")),
        sources=d.get("sources", {}),
        raw=d,
    )
    der = (d.get("sources", {}) or {}).get("deribit", {}) or {}
    if der.get("api_url"):
        api_url = str(der["api_url"])
    elif der.get("base_url"):
        api_url = str(der["base_url"]).rstrip("/") + "/api/v2"
    else:
        api_url = "https://www.deribit.com/api/v2"
    cfg.deribit = DeribitConfig(
        enabled=bool(der.get("enabled", False)),
        api_url=api_url,
        poll_interval_seconds=int(der.get("poll_interval_seconds", 30) or 30),
        stale_threshold_seconds=int(der.get("stale_threshold_seconds", 180) or 180),
        include_in_model_features=bool(der.get("include_in_model_features", False)),
        allow_historical_features_when_disabled=bool(
            der.get("allow_historical_features_when_disabled", False)),
        record_raw=bool(der.get("record_raw", True)),
        record_normalized=bool(der.get("record_normalized", True)),
    )
    return cfg


def _field_names(cls) -> list[str]:
    return [f.name for f in fields(cls)]


def _apply_env_overrides(cfg: AppConfig) -> None:
    """Environment variables override YAML. Secrets only ever come from env."""
    cfg.trading_mode = os.environ.get("TRADING_MODE", cfg.trading_mode)
    cfg.live_trading_enabled = _env_bool("LIVE_TRADING_ENABLED", cfg.live_trading_enabled)
    cfg.require_manual_confirmation = _env_bool(
        "REQUIRE_MANUAL_CONFIRMATION", cfg.require_manual_confirmation
    )
    cfg.kill_switch_enabled = _env_bool("KILL_SWITCH_ENABLED", cfg.kill_switch_enabled)

    cfg.timezone = os.environ.get("LOCAL_TIMEZONE", cfg.timezone)
    cfg.eod_summary_time = os.environ.get("EOD_SUMMARY_TIME", cfg.eod_summary_time)

    # Risk limits
    r = cfg.risk
    for env_name, attr in (
        ("MAX_ORDER_SIZE", "max_order_size"),
        ("MAX_POSITION_PER_CONTRACT", "max_position_per_contract"),
        ("MAX_DAILY_LOSS", "max_daily_loss"),
        ("MAX_OPEN_RISK", "max_open_risk"),
    ):
        v = _env_float(env_name)
        if v is not None:
            setattr(r, attr, v)
    mtph = _env_int("MAX_TRADES_PER_HOUR")
    if mtph is not None:
        r.max_trades_per_hour = mtph

    # Paper
    bankroll = _env_float("PAPER_STARTING_BANKROLL")
    if bankroll is not None:
        cfg.paper_starting_bankroll = bankroll

    # Paths / logging
    cfg.data_dir = os.environ.get("DATA_DIR", cfg.data_dir)
    cfg.reports_dir = os.environ.get("REPORTS_DIR", cfg.reports_dir)
    cfg.log_level = os.environ.get("LOG_LEVEL", cfg.log_level)

    # Notifications — Pushover (secrets from env only)
    n = cfg.notifications
    n.pushover_enabled = _env_bool("PUSHOVER_ENABLED", n.pushover_enabled)
    n.pushover_app_token = os.environ.get("PUSHOVER_APP_TOKEN") or None
    n.pushover_user_key = os.environ.get("PUSHOVER_USER_KEY") or None
    n.pushover_device = os.environ.get("PUSHOVER_DEVICE") or None
    prio = _env_int("PUSHOVER_PRIORITY")
    if prio is not None:
        n.pushover_priority = prio
    n.pushover_sound = os.environ.get("PUSHOVER_SOUND") or None
    n.pushover_api_url = os.environ.get("PUSHOVER_API_URL", n.pushover_api_url)
    n.event_prefix = os.environ.get("NOTIFY_EVENT_PREFIX", n.event_prefix)
    # Async notification queue (latency-safe). Hot path enqueues; worker sends.
    n.async_enabled = _env_bool("NOTIFICATIONS_ASYNC_ENABLED", n.async_enabled)
    _qm = _env_int("NOTIFICATIONS_QUEUE_MAXSIZE")
    if _qm and _qm > 0:
        n.queue_maxsize = _qm
    _st = _env_int("NOTIFICATIONS_SEND_TIMEOUT_MS")
    if _st and _st > 0:
        n.send_timeout_ms = _st
    n.drop_low_priority_when_full = _env_bool(
        "NOTIFICATIONS_DROP_LOW_PRIORITY_WHEN_FULL", n.drop_low_priority_when_full)
    n.coalesce_watch = _env_bool("NOTIFICATIONS_COALESCE_WATCH", n.coalesce_watch)
    n.hotpath_blocking_forbidden = _env_bool(
        "NOTIFICATIONS_HOTPATH_BLOCKING_FORBIDDEN", n.hotpath_blocking_forbidden)

    # Polymarket creds (env only)
    p = cfg.polymarket
    p.api_key = os.environ.get("POLYMARKET_API_KEY") or None
    p.api_secret = os.environ.get("POLYMARKET_API_SECRET") or None
    p.api_passphrase = os.environ.get("POLYMARKET_API_PASSPHRASE") or None
    p.funder_address = os.environ.get("POLYMARKET_FUNDER_ADDRESS") or None
    p.wallet_address = os.environ.get("POLYMARKET_WALLET_ADDRESS") or None
    cfg.polymarket_dormant = _env_bool("POLYMARKET_DORMANT", cfg.polymarket_dormant)

    # Kalshi (public market data needs no secrets; auth is optional, env-only)
    k = cfg.kalshi
    k.env = os.environ.get("KALSHI_ENV", k.env)
    k.api_base = os.environ.get("KALSHI_API_BASE", os.environ.get("KALSHI_API_BASE_URL", k.api_base))
    k.ws_url = os.environ.get("KALSHI_WS_URL", os.environ.get("KALSHI_WEBSOCKET_URL", k.ws_url))
    k.series_ticker = os.environ.get("KALSHI_SERIES_TICKER", k.series_ticker)
    k.key_id = os.environ.get("KALSHI_KEY_ID") or None
    k.private_key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH") or None
    k.private_key_passphrase = os.environ.get("KALSHI_PRIVATE_KEY_PASSPHRASE") or None
    fee_rate = _env_float("KALSHI_FEE_RATE")
    if fee_rate is not None:
        k.fee_rate = fee_rate
    k.fee_status = os.environ.get("KALSHI_FEE_STATUS", k.fee_status)

    # Deribit (OPTIONAL auxiliary; disabled by default; public reads need no creds)
    de = cfg.deribit
    de.enabled = _env_bool("DERIBIT_ENABLED", de.enabled)
    de.api_url = os.environ.get("DERIBIT_API_URL", de.api_url)
    de.client_id = os.environ.get("DERIBIT_CLIENT_ID") or None
    de.client_secret = os.environ.get("DERIBIT_CLIENT_SECRET") or None
    pi = _env_int("DERIBIT_POLL_INTERVAL_SECONDS")
    if pi is not None and pi > 0:
        de.poll_interval_seconds = pi
    st = _env_int("DERIBIT_STALE_THRESHOLD_SECONDS")
    if st is not None and st > 0:
        de.stale_threshold_seconds = st
    # Candidate-feature inclusion is a SEPARATE control from collection. Defaults
    # False; cannot silently become effective while disabled (see
    # DeribitConfig.select_for_model_features + ALLOW_HISTORICAL_FEATURES_WHEN_DISABLED).
    de.include_in_model_features = _env_bool(
        "DERIBIT_INCLUDE_IN_MODEL_FEATURES", de.include_in_model_features)
    de.allow_historical_features_when_disabled = _env_bool(
        "DERIBIT_ALLOW_HISTORICAL_FEATURES_WHEN_DISABLED",
        de.allow_historical_features_when_disabled)
    de.record_raw = _env_bool("DERIBIT_RECORD_RAW", de.record_raw)
    de.record_normalized = _env_bool("DERIBIT_RECORD_NORMALIZED", de.record_normalized)

    # Source freshness: LIVENESS (collector alive) vs DECISION (fresh enough to trade)
    # are separate, explicit thresholds. Defaults are conservative; never loosen the
    # decision thresholds to manufacture trades.
    fr = cfg.freshness
    for env_name, attr in (
        ("KALSHI_BOOK_LIVENESS_THRESHOLD_MS", "kalshi_book_liveness_ms"),
        ("KALSHI_BOOK_DECISION_MAX_AGE_MS", "kalshi_book_decision_max_age_ms"),
        ("COINBASE_LIVENESS_THRESHOLD_MS", "coinbase_liveness_ms"),
        ("COINBASE_DECISION_MAX_AGE_MS", "coinbase_decision_max_age_ms"),
        ("BINANCE_LIVENESS_THRESHOLD_MS", "binance_liveness_ms"),
        ("BINANCE_DECISION_MAX_AGE_MS", "binance_decision_max_age_ms"),
        ("DERIBIT_LIVENESS_THRESHOLD_MS", "deribit_liveness_ms"),
        ("DERIBIT_DECISION_MAX_AGE_MS", "deribit_decision_max_age_ms"),
        ("KALSHI_FEATURE_ROW_MAX_AGE_MS", "feature_row_max_age_ms"),
    ):
        v = _env_int(env_name)
        if v is not None and v > 0:
            setattr(fr, attr, v)
    fr.underlying_require_one_fresh = _env_bool("UNDERLYING_REQUIRE_ONE_FRESH", fr.underlying_require_one_fresh)
    fr.underlying_primary = os.environ.get("UNDERLYING_PRIMARY", fr.underlying_primary).strip().lower()
    fr.underlying_fallback = os.environ.get("UNDERLYING_FALLBACK", fr.underlying_fallback).strip().lower()
    fr.underlying_allow_binance_fallback = _env_bool("UNDERLYING_ALLOW_BINANCE_FALLBACK", fr.underlying_allow_binance_fallback)
    fr.underlying_require_primary_for_entry = _env_bool("UNDERLYING_REQUIRE_PRIMARY_FOR_ENTRY", fr.underlying_require_primary_for_entry)
    fr.underlying_reject_if_both_stale = _env_bool("UNDERLYING_REJECT_IF_BOTH_STALE", fr.underlying_reject_if_both_stale)
    fr.reject_paper_if_book_stale = _env_bool("KALSHI_REJECT_PAPER_IF_BOOK_STALE", fr.reject_paper_if_book_stale)
    fr.reject_paper_if_underlying_stale = _env_bool("KALSHI_REJECT_PAPER_IF_UNDERLYING_STALE", fr.reject_paper_if_underlying_stale)
    fr.reject_paper_if_feature_row_stale = _env_bool("KALSHI_REJECT_PAPER_IF_FEATURE_ROW_STALE", fr.reject_paper_if_feature_row_stale)

    # Paper experiment (controlled shadow->paper; NEVER live). Safe defaults.
    xc = cfg.paper_experiment
    xc.enabled = _env_bool("KALSHI_PAPER_EXPERIMENT_ENABLED", xc.enabled)
    _xmode = (os.environ.get("KALSHI_PAPER_EXPERIMENT_MODE", xc.mode) or "shadow").strip().lower()
    xc.mode = _xmode if _xmode in ("disabled", "shadow", "paper") else "shadow"
    xc.name = os.environ.get("KALSHI_PAPER_EXPERIMENT_NAME", xc.name)
    for env_name, attr in (
        ("KALSHI_PAPER_EXPERIMENT_MAX_DURATION_MINUTES", "max_duration_minutes"),
        ("KALSHI_PAPER_EXPERIMENT_MAX_DAILY_TRADES", "max_daily_trades"),
        ("KALSHI_PAPER_EXPERIMENT_MAX_TRADES_PER_WINDOW", "max_trades_per_window"),
        ("KALSHI_PAPER_EXPERIMENT_MAX_OPEN_POSITIONS", "max_open_positions"),
        ("KALSHI_PAPER_EXPERIMENT_COOLDOWN_SECONDS", "cooldown_seconds"),
        ("KALSHI_PAPER_EXPERIMENT_MIN_SECONDS_TO_CLOSE", "min_seconds_to_close"),
        ("KALSHI_PAPER_EXPERIMENT_MAX_SECONDS_TO_CLOSE", "max_seconds_to_close"),
        ("KALSHI_PAPER_EXPERIMENT_MAX_BOOK_AGE_MS", "max_book_age_ms"),
        ("KALSHI_PAPER_EXPERIMENT_MAX_UNDERLYING_AGE_MS", "max_underlying_age_ms"),
        ("KALSHI_PAPER_EXPERIMENT_MAX_DERIBIT_AGE_MS", "max_deribit_age_ms"),
        ("KALSHI_PAPER_EXPERIMENT_MAX_CONSECUTIVE_REJECTIONS", "max_consecutive_rejections"),
    ):
        v = _env_int(env_name)
        if v is not None:
            setattr(xc, attr, v)
    for env_name, attr in (
        ("KALSHI_PAPER_EXPERIMENT_DEFAULT_SIZE", "default_size"),
        ("KALSHI_PAPER_EXPERIMENT_MIN_NET_EDGE_CENTS", "min_net_edge_cents"),
        ("KALSHI_PAPER_EXPERIMENT_MIN_FINAL_EDGE_CENTS", "min_final_edge_cents"),
        ("KALSHI_PAPER_EXPERIMENT_MIN_RAW_EDGE_CENTS", "min_raw_edge_cents"),
        ("KALSHI_PAPER_EXPERIMENT_MAX_DRAWDOWN_CENTS", "max_drawdown_cents"),
        ("KALSHI_PAPER_EXPERIMENT_MAX_DAILY_PAPER_LOSS_CENTS", "max_daily_paper_loss_cents"),
    ):
        v = _env_float(env_name)
        if v is not None:
            setattr(xc, attr, v)
    xc.require_promoted_model = _env_bool("KALSHI_PAPER_EXPERIMENT_REQUIRE_PROMOTED_MODEL", xc.require_promoted_model)
    xc.require_calibrator = _env_bool("KALSHI_PAPER_EXPERIMENT_REQUIRE_CALIBRATOR", xc.require_calibrator)
    xc.require_edge_policy = _env_bool("KALSHI_PAPER_EXPERIMENT_REQUIRE_EDGE_POLICY", xc.require_edge_policy)
    xc.require_source_freshness = _env_bool("KALSHI_PAPER_EXPERIMENT_REQUIRE_SOURCE_FRESHNESS", xc.require_source_freshness)
    xc.require_backtest_report = _env_bool("KALSHI_PAPER_EXPERIMENT_REQUIRE_BACKTEST_REPORT", xc.require_backtest_report)
    xc.allow_diagnostic = _env_bool("KALSHI_PAPER_EXPERIMENT_ALLOW_DIAGNOSTIC", xc.allow_diagnostic)
    # allow_live is intentionally NOT read from env — experiments are never live.
    xc.abort_on_source_stale = _env_bool("KALSHI_PAPER_EXPERIMENT_ABORT_ON_SOURCE_STALE", xc.abort_on_source_stale)
    xc.abort_on_model_error = _env_bool("KALSHI_PAPER_EXPERIMENT_ABORT_ON_MODEL_ERROR", xc.abort_on_model_error)
    xc.abort_on_policy_error = _env_bool("KALSHI_PAPER_EXPERIMENT_ABORT_ON_POLICY_ERROR", xc.abort_on_policy_error)
    xc.abort_on_unexpected_live_enabled = _env_bool(
        "KALSHI_PAPER_EXPERIMENT_ABORT_ON_UNEXPECTED_LIVE_ENABLED", xc.abort_on_unexpected_live_enabled)

    # Low-latency hot path (OPTIONAL; SAFE/disabled by default; never live).
    ll = cfg.low_latency
    ll.enabled = _env_bool("KALSHI_LOW_LATENCY_ENABLED", ll.enabled)
    ll.use_websocket = _env_bool("KALSHI_USE_WEBSOCKET", ll.use_websocket)
    ll.rest_fallback_enabled = _env_bool("KALSHI_REST_FALLBACK_ENABLED", ll.rest_fallback_enabled)
    ll.profile = _env_bool("KALSHI_HOTPATH_PROFILE", ll.profile)
    ll.paper_only = _env_bool("KALSHI_HOTPATH_PAPER_ONLY", ll.paper_only)
    ll.order_planning_enabled = _env_bool("KALSHI_ORDER_PLANNING_ENABLED", ll.order_planning_enabled)
    for env_name, attr in (
        ("KALSHI_HOTPATH_SCORE_INTERVAL_MS", "hotpath_score_interval_ms"),
        ("KALSHI_MAX_BOOK_AGE_MS", "max_book_age_ms"),
        ("KALSHI_MAX_UNDERLYING_AGE_MS", "max_underlying_age_ms"),
        ("KALSHI_MAX_DERIBIT_AGE_MS", "max_deribit_age_ms"),
        ("KALSHI_HOTPATH_LOG_EVERY_N", "log_every_n"),
        ("KALSHI_MARKET_DURATION_SECONDS", "market_duration_seconds"),
        ("KALSHI_MIN_SECONDS_TO_CLOSE", "min_seconds_to_close"),
        ("KALSHI_MAX_SECONDS_TO_CLOSE", "max_seconds_to_close"),
    ):
        v = _env_int(env_name)
        if v is not None:
            setattr(ll, attr, v)
    me = _env_float("KALSHI_MIN_NET_EDGE_CENTS")
    if me is not None:
        ll.min_net_edge_cents = me
    md = _env_float("KALSHI_MIN_DEPTH")
    if md is not None:
        ll.min_depth = md
    tif = os.environ.get("KALSHI_ALLOWED_TIME_IN_FORCE")
    if tif and tif.strip():
        ll.allowed_time_in_force = tuple(s.strip() for s in tif.split(",") if s.strip())

    # Calibration + executable backtest (RESEARCH ONLY; never trades).
    bt = cfg.backtest
    for env_name, attr in (
        ("KALSHI_BACKTEST_MIN_WINDOWS", "min_windows"),
        ("KALSHI_TRAIN_MIN_WINDOWS", "train_min_windows"),
        ("KALSHI_CALIBRATION_MIN_WINDOWS", "calibration_min_windows"),
        ("KALSHI_BACKTEST_MAX_BOOK_AGE_MS", "max_book_age_ms"),
        ("KALSHI_BACKTEST_MAX_UNDERLYING_AGE_MS", "max_underlying_age_ms"),
        ("KALSHI_BACKTEST_MIN_SECONDS_TO_CLOSE", "min_seconds_to_close"),
        ("KALSHI_BACKTEST_MAX_SECONDS_TO_CLOSE", "max_seconds_to_close"),
    ):
        v = _env_int(env_name)
        if v is not None:
            setattr(bt, attr, v)
    for env_name, attr in (
        ("KALSHI_BACKTEST_DEFAULT_SIZE", "default_size"),
        ("KALSHI_BACKTEST_MIN_NET_EDGE_CENTS", "min_net_edge_cents"),
        ("KALSHI_BACKTEST_MAX_SPREAD", "max_spread"),
        ("KALSHI_BACKTEST_MIN_DEPTH", "min_depth"),
    ):
        v = _env_float(env_name)
        if v is not None:
            setattr(bt, attr, v)
    bt.allow_diagnostic = _env_bool("KALSHI_BACKTEST_ALLOW_DIAGNOSTIC", bt.allow_diagnostic)
    bt.use_deribit_filters = _env_bool("KALSHI_BACKTEST_USE_DERIBIT_FILTERS", bt.use_deribit_filters)

    # Paper-candidate policy (CONSERVATIVE/disabled by default; never live).
    pp = cfg.paper_policy
    pp.enabled = _env_bool("KALSHI_PAPER_POLICY_ENABLED", pp.enabled)
    pp.require_trained_model = _env_bool("KALSHI_REQUIRE_TRAINED_MODEL", pp.require_trained_model)
    pp.require_calibrated_model = _env_bool("KALSHI_REQUIRE_CALIBRATED_MODEL", pp.require_calibrated_model)
    pp.require_backtest_evidence = _env_bool("KALSHI_REQUIRE_BACKTEST_EVIDENCE", pp.require_backtest_evidence)
    pp.require_non_diagnostic_model = _env_bool("KALSHI_REQUIRE_NON_DIAGNOSTIC_MODEL", pp.require_non_diagnostic_model)
    pp.require_deribit_fresh = _env_bool("KALSHI_REQUIRE_DERIBIT_FRESH", pp.require_deribit_fresh)
    pp.allow_diagnostic_paper = _env_bool("KALSHI_ALLOW_DIAGNOSTIC_PAPER", pp.allow_diagnostic_paper)
    pp.notify_paper_candidates = _env_bool("KALSHI_NOTIFY_PAPER_CANDIDATES", pp.notify_paper_candidates)
    # paper promotion + runtime gates (paper-only)
    pp.promotion_required = _env_bool("KALSHI_PAPER_PROMOTION_REQUIRED", pp.promotion_required)
    pp.require_promoted_paper_model = _env_bool("KALSHI_REQUIRE_PROMOTED_PAPER_MODEL", pp.require_promoted_paper_model)
    pp.require_edge_policy = _env_bool("KALSHI_REQUIRE_EDGE_POLICY", pp.require_edge_policy)
    pp.require_frequency_report = _env_bool("KALSHI_REQUIRE_FREQUENCY_REPORT", pp.require_frequency_report)
    _mdt = _env_int("KALSHI_MAX_DAILY_TRADES")
    if _mdt is not None:
        pp.max_daily_trades = _mdt
    _ecs = _env_int("KALSHI_ENTRY_COOLDOWN_SECONDS")
    if _ecs is not None:
        pp.entry_cooldown_seconds = _ecs
    # Model runtime mode (disabled | shadow | paper). "live" is never accepted here.
    _mode = (os.environ.get("KALSHI_MODEL_RUNTIME_MODE", cfg.model_runtime_mode) or "disabled").strip().lower()
    cfg.model_runtime_mode = _mode if _mode in ("disabled", "shadow", "paper") else "disabled"
    for env_name, attr in (
        ("KALSHI_MIN_CALIBRATION_WINDOWS", "min_calibration_windows"),
        ("KALSHI_MIN_BACKTEST_WINDOWS", "min_backtest_windows"),
        ("KALSHI_MAX_BOOK_AGE_MS", "max_book_age_ms"),
        ("KALSHI_MAX_UNDERLYING_AGE_MS", "max_underlying_age_ms"),
        ("KALSHI_MAX_DERIBIT_AGE_MS", "max_deribit_age_ms"),
        ("KALSHI_MIN_SECONDS_TO_CLOSE", "min_seconds_to_close"),
        ("KALSHI_MAX_SECONDS_TO_CLOSE", "max_seconds_to_close"),
        ("KALSHI_MAX_TRADES_PER_WINDOW", "max_trades_per_window"),
        ("KALSHI_MAX_OPEN_POSITIONS", "max_open_positions"),
    ):
        v = _env_int(env_name)
        if v is not None:
            setattr(pp, attr, v)
    for env_name, attr in (
        ("KALSHI_MIN_NET_EDGE_CENTS", "min_net_edge_cents"),
        ("KALSHI_MIN_RAW_EDGE_CENTS", "min_raw_edge_cents"),
        ("KALSHI_UNCERTAINTY_BUFFER_CENTS", "uncertainty_buffer_cents"),
        ("KALSHI_SLIPPAGE_BUFFER_CENTS", "slippage_buffer_cents"),
        ("KALSHI_MAX_YES_PRICE_CENTS", "max_yes_price_cents"),
        ("KALSHI_MAX_NO_PRICE_CENTS", "max_no_price_cents"),
        ("KALSHI_MAX_SPREAD_CENTS", "max_spread_cents"),
        ("KALSHI_MIN_TOP_DEPTH_CONTRACTS", "min_top_depth_contracts"),
        ("KALSHI_MAX_POSITION_PER_CONTRACT", "max_position_per_contract"),
        ("KALSHI_PAPER_DEFAULT_SIZE", "paper_default_size"),
    ):
        v = _env_float(env_name)
        if v is not None:
            setattr(pp, attr, v)

    # Post-entry lock-profit module (paper-only; disabled by default; never live).
    lk = cfg.lock
    lk.enabled = _env_bool("KALSHI_LOCK_MODULE_ENABLED", lk.enabled)
    lk.paper_only = _env_bool("KALSHI_LOCK_PAPER_ONLY", lk.paper_only)
    lk.allow_partial = _env_bool("KALSHI_LOCK_ALLOW_PARTIAL", lk.allow_partial)
    lk.require_underlying_fresh = _env_bool("KALSHI_LOCK_REQUIRE_UNDERLYING_FRESH", lk.require_underlying_fresh)
    lk.notify = _env_bool("KALSHI_LOCK_NOTIFY", lk.notify)
    lk.default_mode = os.environ.get("KALSHI_LOCK_DEFAULT_MODE", lk.default_mode).lower()
    for env_name, attr in (
        ("KALSHI_LOCK_MAX_BOOK_AGE_MS", "max_book_age_ms"),
        ("KALSHI_LOCK_MAX_UNDERLYING_AGE_MS", "max_underlying_age_ms"),
        ("KALSHI_LOCK_MIN_SECONDS_TO_CLOSE", "min_seconds_to_close"),
    ):
        v = _env_int(env_name)
        if v is not None:
            setattr(lk, attr, v)
    for env_name, attr in (
        ("KALSHI_LOCK_MIN_PROFIT_CENTS", "min_profit_cents"),
        ("KALSHI_LOCK_HARD_PROFIT_CENTS", "hard_profit_cents"),
        ("KALSHI_LOCK_MIN_DEPTH_CONTRACTS", "min_depth_contracts"),
        ("KALSHI_LOCK_RIDE_MIN_EDGE_CENTS", "ride_min_edge_cents"),
        ("KALSHI_LOCK_FORCE_WHEN_MODEL_EDGE_BELOW_CENTS", "force_when_model_edge_below_cents"),
        ("KALSHI_LOCK_SLIPPAGE_BUFFER_CENTS", "slippage_buffer_cents"),
    ):
        v = _env_float(env_name)
        if v is not None:
            setattr(lk, attr, v)

    # ----- position lifecycle manager (post-entry; paper-only) -----
    lc = cfg.lifecycle
    lc.enabled = _env_bool("KALSHI_POSITION_LIFECYCLE_ENABLED", lc.enabled)
    lc.paper_only = _env_bool("KALSHI_POSITION_LIFECYCLE_PAPER_ONLY", lc.paper_only)
    lc.allow_partial_exit = _env_bool("KALSHI_LIFECYCLE_ALLOW_PARTIAL_EXIT", lc.allow_partial_exit)
    lc.allow_partial_lock = _env_bool("KALSHI_LIFECYCLE_ALLOW_PARTIAL_LOCK", lc.allow_partial_lock)
    lc.notify = _env_bool("KALSHI_LIFECYCLE_NOTIFY", lc.notify)
    lc.default_tif = os.environ.get("KALSHI_LIFECYCLE_DEFAULT_TIF", lc.default_tif).lower()
    for env_name, attr in (
        ("KALSHI_LIFECYCLE_MAX_BOOK_AGE_MS", "max_book_age_ms"),
        ("KALSHI_LIFECYCLE_MAX_UNDERLYING_AGE_MS", "max_underlying_age_ms"),
        ("KALSHI_LIFECYCLE_MIN_SECONDS_TO_CLOSE", "min_seconds_to_close"),
    ):
        v = _env_int(env_name)
        if v is not None:
            setattr(lc, attr, v)
    for env_name, attr in (
        ("KALSHI_LIFECYCLE_MIN_SELL_PROFIT_CENTS", "min_sell_profit_cents"),
        ("KALSHI_LIFECYCLE_HARD_SELL_PROFIT_CENTS", "hard_sell_profit_cents"),
        ("KALSHI_LIFECYCLE_MIN_LOCK_PROFIT_CENTS", "min_lock_profit_cents"),
        ("KALSHI_LIFECYCLE_HARD_LOCK_PROFIT_CENTS", "hard_lock_profit_cents"),
        ("KALSHI_LIFECYCLE_RIDE_MIN_EDGE_CENTS", "ride_min_edge_cents"),
        ("KALSHI_LIFECYCLE_FORCE_EXIT_WHEN_MODEL_EDGE_BELOW_CENTS", "force_exit_when_model_edge_below_cents"),
        ("KALSHI_LIFECYCLE_FORCE_LOCK_WHEN_MODEL_EDGE_BELOW_CENTS", "force_lock_when_model_edge_below_cents"),
        ("KALSHI_LIFECYCLE_MIN_DEPTH_CONTRACTS", "min_depth_contracts"),
        ("KALSHI_LIFECYCLE_MAX_SPREAD_CENTS", "max_spread_cents"),
    ):
        v = _env_float(env_name)
        if v is not None:
            setattr(lc, attr, v)

    # ----- trade-frequency analysis (research/reporting only) -----
    fq = cfg.frequency
    fq.enabled = _env_bool("KALSHI_FREQUENCY_ANALYSIS_ENABLED", fq.enabled)
    fq.do_not_promote = _env_bool("KALSHI_FREQ_DO_NOT_PROMOTE", fq.do_not_promote)
    _fms = _env_int("KALSHI_FREQ_DEFAULT_MAX_SCENARIOS")
    if _fms and _fms > 0:
        fq.default_max_scenarios = _fms

    def _csv_nums(name, cur, cast):
        raw = os.environ.get(name)
        if not raw:
            return cur
        try:
            return tuple(cast(x) for x in raw.split(",") if x.strip())
        except ValueError:
            return cur
    fq.min_net_edge_grid_cents = _csv_nums("KALSHI_FREQ_MIN_NET_EDGE_GRID_CENTS", fq.min_net_edge_grid_cents, float)
    fq.max_trades_per_window_grid = _csv_nums("KALSHI_FREQ_MAX_TRADES_PER_WINDOW_GRID", fq.max_trades_per_window_grid, lambda x: int(float(x)))
    fq.cooldown_grid_seconds = _csv_nums("KALSHI_FREQ_COOLDOWN_GRID_SECONDS", fq.cooldown_grid_seconds, lambda x: int(float(x)))
    fq.min_seconds_to_close_grid = _csv_nums("KALSHI_FREQ_MIN_SECONDS_TO_CLOSE_GRID", fq.min_seconds_to_close_grid, lambda x: int(float(x)))
    fq.report_top_n = _csv_nums("KALSHI_FREQ_REPORT_TOP_N", fq.report_top_n, lambda x: int(float(x)))

    # ----- confidence-aware edge threshold / reservation-price policy -----
    ep = cfg.edge_policy
    ep.enabled = _env_bool("KALSHI_EDGE_POLICY_ENABLED", ep.enabled)
    ep.require_confidence_bounds = _env_bool("KALSHI_EDGE_REQUIRE_CONFIDENCE_BOUNDS", ep.require_confidence_bounds)
    ep.use_calibration_buckets = _env_bool("KALSHI_EDGE_USE_CALIBRATION_BUCKETS", ep.use_calibration_buckets)
    ep.use_window_bootstrap = _env_bool("KALSHI_EDGE_USE_WINDOW_BOOTSTRAP", ep.use_window_bootstrap)
    ep.use_ensemble_disagreement = _env_bool("KALSHI_EDGE_USE_ENSEMBLE_DISAGREEMENT", ep.use_ensemble_disagreement)
    ep.report_breakdown = _env_bool("KALSHI_EDGE_REPORT_BREAKDOWN", ep.report_breakdown)
    _ru = os.environ.get("KALSHI_EDGE_RELIABILITY_UNIT", ep.reliability_unit).strip().lower()
    ep.reliability_unit = _ru if _ru in ("row", "window", "both") else "both"
    for env_name, attr in (
        ("KALSHI_EDGE_MIN_CALIBRATION_BUCKET_N", "min_calibration_bucket_n"),
        ("KALSHI_EDGE_BOOTSTRAP_SAMPLES", "bootstrap_samples"),
        ("KALSHI_EDGE_MAX_BOOK_AGE_MS", "max_book_age_ms"),
        ("KALSHI_EDGE_MAX_UNDERLYING_AGE_MS", "max_underlying_age_ms"),
    ):
        v = _env_int(env_name)
        if v is not None:
            setattr(ep, attr, v)
    for env_name, attr in (
        ("KALSHI_EDGE_MIN_RAW_EDGE_CENTS", "min_raw_edge_cents"),
        ("KALSHI_EDGE_MIN_FINAL_EDGE_CENTS", "min_final_edge_cents"),
        ("KALSHI_EDGE_BASE_MIN_PROFIT_CENTS", "base_min_profit_cents"),
        ("KALSHI_EDGE_FIXED_UNCERTAINTY_BUFFER_CENTS", "fixed_uncertainty_buffer_cents"),
        ("KALSHI_EDGE_CONFIDENCE_LEVEL", "confidence_level"),
        ("KALSHI_EDGE_MAX_PROB_INTERVAL_WIDTH_CENTS", "max_prob_interval_width_cents"),
        ("KALSHI_EDGE_MAX_MODEL_DISAGREEMENT_CENTS", "max_model_disagreement_cents"),
        ("KALSHI_EDGE_STALE_QUOTE_BUFFER_CENTS", "stale_quote_buffer_cents"),
        ("KALSHI_EDGE_SOURCE_STALE_BUFFER_CENTS", "source_stale_buffer_cents"),
        ("KALSHI_EDGE_HIGH_VOL_REGIME_BUFFER_CENTS", "high_vol_regime_buffer_cents"),
        ("KALSHI_EDGE_THIN_BOOK_BUFFER_CENTS", "thin_book_buffer_cents"),
        ("KALSHI_EDGE_OVERTRADING_BUFFER_CENTS", "overtrading_buffer_cents"),
        ("KALSHI_EDGE_MIN_BOOK_DEPTH", "min_book_depth"),
        ("KALSHI_EDGE_MAX_SPREAD_CENTS", "max_spread_cents"),
    ):
        v = _env_float(env_name)
        if v is not None:
            setattr(ep, attr, v)

    # Live-readiness scaffolding (SAFE/locked by default; NEVER submits).
    lr = cfg.live_readiness
    lr.enabled = _env_bool("KALSHI_LIVE_READINESS_ENABLED", lr.enabled)
    lr.dry_run_only = _env_bool("KALSHI_LIVE_DRY_RUN_ONLY", lr.dry_run_only)
    lr.submit_enabled = _env_bool("KALSHI_LIVE_SUBMIT_ENABLED", lr.submit_enabled)
    lr.allow_private_reads = _env_bool("KALSHI_LIVE_ALLOW_PRIVATE_READS", lr.allow_private_reads)
    lr.require_approved_model = _env_bool("KALSHI_REQUIRE_APPROVED_MODEL", lr.require_approved_model)
    lr.require_valid_calibrator = _env_bool("KALSHI_REQUIRE_VALID_CALIBRATOR", lr.require_valid_calibrator)
    lr.require_valid_backtest = _env_bool("KALSHI_REQUIRE_VALID_BACKTEST", lr.require_valid_backtest)
    lr.require_paper_evidence = _env_bool("KALSHI_REQUIRE_PAPER_EVIDENCE", lr.require_paper_evidence)
    lr.require_source_health = _env_bool("KALSHI_REQUIRE_SOURCE_HEALTH", lr.require_source_health)
    lr.require_fresh_book = _env_bool("KALSHI_REQUIRE_FRESH_BOOK", lr.require_fresh_book)
    lr.require_limit_order = _env_bool("KALSHI_REQUIRE_LIMIT_ORDER", lr.require_limit_order)
    lr.require_fok_or_ioc = _env_bool("KALSHI_REQUIRE_FOK_OR_IOC", lr.require_fok_or_ioc)
    lr.allow_market_orders = _env_bool("KALSHI_ALLOW_MARKET_ORDERS", lr.allow_market_orders)
    pt = _env_int("KALSHI_LIVE_PRECHECK_TIMEOUT_MS")
    if pt is not None:
        lr.precheck_timeout_ms = pt
    for env_name, attr in (
        ("KALSHI_MAX_LIVE_ORDER_SIZE", "max_live_order_size"),
        ("KALSHI_MAX_LIVE_NOTIONAL", "max_live_notional"),
        ("KALSHI_MAX_LIVE_DAILY_LOSS", "max_live_daily_loss"),
        ("KALSHI_MAX_LIVE_OPEN_EXPOSURE", "max_live_open_exposure"),
    ):
        v = _env_float(env_name)
        if v is not None:
            setattr(lr, attr, v)
