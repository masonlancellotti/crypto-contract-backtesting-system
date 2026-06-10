"""Trade-frequency frontier / overtrading analysis (RESEARCH EVIDENCE ONLY).

Principle: **scoring frequency should be high; trade frequency must be earned.**
The system evaluates constantly, but a marginal (paper) trade is only worth taking
when it still has positive expected value after fees, executable bid/ask, spread,
depth, freshness, model uncertainty, and — crucially — *correlation* with other
trades in the same 15-minute window.

This module measures the relationship between trade frequency and net performance
on a leakage-safe, held-out evaluation set. It never trades, never promotes a
policy, never enables live. It reuses the executable backtest engine
(:mod:`executable_backtest`) for candidate edges (executable asks, never midpoint)
and settlement P&L vs the OFFICIAL label.

Independence caveat baked in everywhere: N entries inside ONE 15-minute window all
settle to the SAME label, so they are NOT N independent samples. Reports always
separate raw trades from **distinct windows** and warn on concentration.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .executable_backtest import BacktestParams, evaluate_row, settle_trade, _prob_for
from .fees import KalshiFeeModel

# Time-to-close buckets (seconds remaining). Order matters (longest -> shortest).
TTC_BUCKETS = [
    ("15m-10m", 600, 900), ("10m-5m", 300, 600), ("5m-2m", 120, 300),
    ("2m-60s", 60, 120), ("60s-30s", 30, 60), ("30s-10s", 10, 30),
    ("10s-5s", 5, 10), ("<5s", 0, 5),
]
PROB_BUCKETS = [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70),
                (0.70, 0.80), (0.80, 0.90), (0.90, 1.01)]


def ttc_bucket(secs: Optional[float]) -> str:
    if secs is None:
        return "na"
    for name, lo, hi in TTC_BUCKETS:
        if lo <= secs < hi:
            return name
    return ">=15m" if secs >= 900 else "closed"


def prob_bucket(p: Optional[float]) -> str:
    if p is None:
        return "na"
    for lo, hi in PROB_BUCKETS:
        if lo <= p < hi:
            return f"{int(lo*100)}-{int(hi*100) if hi <= 1 else 100}%"
    return "<50%" if p < 0.50 else "na"


# --------------------------------------------------------------------------- #
# Config + scenario structures
# --------------------------------------------------------------------------- #
@dataclass
class FrequencyScenario:
    name: str = "base"
    min_net_edge_cents: float = 2.0
    min_raw_edge_cents: float = 0.0
    max_trades_per_window: int = 1
    max_entries_per_window: int = 1
    max_exits_or_locks_per_window: int = 1
    cooldown_after_entry_seconds: float = 0.0
    cooldown_after_reject_seconds: float = 0.0
    cooldown_after_exit_seconds: float = 0.0
    min_seconds_to_close: float = 5.0
    max_seconds_to_close: float = 900.0
    max_book_age_ms: int = 1000
    max_underlying_age_ms: int = 2000
    max_deribit_age_ms: int = 180_000
    min_depth: float = 1.0
    max_spread_cents: float = 10.0
    allow_reentry_after_exit: bool = False
    allow_multiple_entries_same_window: bool = False
    require_different_side_for_reentry: bool = False
    max_daily_trades: int = 100
    max_open_positions: int = 1
    max_position_per_window: float = 1.0
    use_deribit_regime_filter: bool = False
    allowed_time_to_close_bucket: Optional[str] = None
    model_id: Optional[str] = None
    calibrator_id: Optional[str] = None
    backtest_id: Optional[str] = None


@dataclass
class FrequencyConfig:
    enabled: bool = True
    default_max_scenarios: int = 250
    min_net_edge_grid_cents: tuple = (1, 2, 3, 5, 7, 10)
    max_trades_per_window_grid: tuple = (1, 2, 3, 5)
    cooldown_grid_seconds: tuple = (0, 5, 15, 30, 60)
    min_seconds_to_close_grid: tuple = (5, 15, 30, 60, 120)
    report_top_n: tuple = (5, 10, 20, 50, 100)
    do_not_promote: bool = True

    @classmethod
    def from_app(cls, config) -> "FrequencyConfig":
        c = getattr(config, "frequency", None)
        if c is None:
            return cls()
        return cls(**{f: getattr(c, f) for f in cls.__dataclass_fields__ if hasattr(c, f)})


@dataclass
class FrequencyResult:
    scenario: str
    trades: int
    distinct_windows: int
    distinct_days: int
    trades_per_window: Optional[float]
    raw_trades_per_day: Optional[float]
    distinct_windows_per_day: Optional[float]
    fraction_same_window: Optional[float]   # share of trades that are NOT new windows
    net_pnl: float
    hit_rate: Optional[float]
    avg_net_edge_cents: Optional[float]
    realized_pnl_per_contract: Optional[float]
    max_drawdown: float
    params: dict = field(default_factory=dict)


@dataclass
class MarginalTradeBucket:
    label: str
    trades: int
    distinct_windows: int
    trades_per_window: Optional[float]
    fraction_same_window: Optional[float]
    cumulative_net_pnl: float
    incremental_net_pnl: Optional[float]
    avg_net_edge_cents: Optional[float]
    realized_pnl_per_contract: Optional[float]
    hit_rate: Optional[float]
    max_drawdown: float


@dataclass
class MarginalTradeCurve:
    buckets: list
    peak_cumulative_net_pnl: float
    peak_at_rank: int                      # adding trades beyond this rank reduced net P&L
    total_candidates: int
    distinct_windows: int
    warnings: list = field(default_factory=list)


@dataclass
class TradeFrequencyBucket:
    bucket: str
    candidates: int
    executed: int
    distinct_windows: int
    net_pnl: float
    hit_rate: Optional[float]
    mean_net_edge_cents: Optional[float]
    avg_fee: Optional[float]
    book_invalid_rate: Optional[float]
    source_stale_rate: Optional[float]
    top_reject_reasons: dict = field(default_factory=dict)


@dataclass
class OvertradingWarning:
    code: str
    message: str
    severity: str = "warn"


@dataclass
class FrequencyFrontierReport:
    series: str
    input_source: str
    prob_source: str
    diagnostic: bool
    tradable: bool
    gate_windows: int
    candidate_count: int
    distinct_windows: int
    distinct_days: int
    scenarios: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    blockers: list = field(default_factory=list)


def _utc_day(ts_ms: Optional[int]) -> str:
    if not ts_ms:
        return "na"
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y%m%d")


# --------------------------------------------------------------------------- #
# Candidate extraction (gate-passing rows with executable net edge + side)
# --------------------------------------------------------------------------- #
def extract_candidates(eval_rows: list[dict], fee_model: KalshiFeeModel, *, size: float = 1.0) -> list[dict]:
    """Every row that passes the HARD executability gates, with its net edge/side.

    Frequency/edge/cap/cooldown gates are applied later per scenario — here we only
    require an executable, labelled, fresh book so the candidate universe is well
    defined. Uses :func:`evaluate_row` with relaxed thresholds (no midpoint)."""
    permissive = BacktestParams(
        size=size, min_net_edge_cents=-1e9, max_book_age_ms=10**12,
        max_underlying_age_ms=10**12, min_seconds_to_close=0, max_seconds_to_close=10**9,
        max_spread=1e9, min_depth=0.0, one_per_window=False)
    out: list[dict] = []
    for r in eval_rows:
        p = _prob_for(r)
        dec = evaluate_row(r, p, permissive, fee_model)
        if not dec["tradeable"]:
            continue
        spread = max(r.get("yes_spread") or 0.0, r.get("no_spread") or 0.0)
        out.append({
            "ticker": r.get("ticker"), "as_of_ts_ms": r.get("as_of_ts_ms"),
            "day": _utc_day(r.get("as_of_ts_ms")), "seconds_to_close": r.get("seconds_to_close"),
            "side": dec["side"], "entry_price": dec["entry_price"],
            "net_edge": dec["net_edge"], "raw_edge": dec["raw_edge"],
            "fee_per_contract": dec["fee_per_contract"], "p_yes": p,
            "label_yes": int(r["label_yes_resolved"]),
            "book_age_ms": r.get("book_age_ms"), "spread_cents": (spread * 100.0) if spread else None,
            "depth": r.get("top_depth"), "distance_to_start": r.get("distance_to_start"),
            "deribit_regime": r.get("deribit_regime"),
            "coinbase_stale": bool(r.get("coinbase_stale")), "binance_stale": bool(r.get("binance_stale")),
            "yes_ask": r.get("yes_ask"), "no_ask": r.get("no_ask"),
        })
    return out


def _settle(c: dict, fee_model: KalshiFeeModel, size: float) -> dict:
    fee_total = fee_model.taker_fee(c["entry_price"], size)
    s = settle_trade(c["side"], c["entry_price"], size, c["label_yes"], fee_total)
    return {**c, "net_pnl": s["net_pnl"], "win": s["win"], "fee_total": fee_total}


def _drawdown(trades: list[dict]) -> float:
    cum = peak = mdd = 0.0
    for t in sorted(trades, key=lambda x: (x.get("as_of_ts_ms") or 0)):
        cum += t["net_pnl"]
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return round(mdd, 6)


def _trade_stats(trades: list[dict]) -> dict:
    n = len(trades)
    wins = sum(1 for t in trades if t.get("win"))
    windows = {t["ticker"] for t in trades}
    days = {t["day"] for t in trades}
    net = sum(t["net_pnl"] for t in trades)
    return {
        "trades": n, "distinct_windows": len(windows), "distinct_days": len(days),
        "net_pnl": round(net, 6), "hit_rate": (wins / n) if n else None,
        "avg_net_edge_cents": (sum((t["net_edge"] or 0) for t in trades) / n * 100.0) if n else None,
        "realized_pnl_per_contract": (net / n) if n else None,
        "trades_per_window": (n / len(windows)) if windows else None,
        "fraction_same_window": (1.0 - len(windows) / n) if n else None,
        "max_drawdown": _drawdown(trades),
    }


# --------------------------------------------------------------------------- #
# Part C — frequency scenario simulation + grid
# --------------------------------------------------------------------------- #
def simulate_frequency_policy(candidates: list[dict], scenario: FrequencyScenario,
                              fee_model: KalshiFeeModel, *, size: float = 1.0) -> FrequencyResult:
    """Apply a frequency policy (edge/caps/cooldowns/daily) to candidates; settle each
    accepted entry vs its window label. Time-ordered; per-window + per-day state."""
    cands = sorted(candidates, key=lambda c: (c["as_of_ts_ms"] or 0))
    win_entries: Counter = Counter()
    win_last_entry: dict = {}
    win_last_reject: dict = {}
    win_sides: dict = defaultdict(set)
    day_count: Counter = Counter()
    accepted: list[dict] = []
    for c in cands:
        secs, tk, ts = c["seconds_to_close"], c["ticker"], c["as_of_ts_ms"]
        net_c = (c["net_edge"] or -9.0) * 100.0
        raw_c = (c["raw_edge"] or -9.0) * 100.0
        reject = False
        if net_c < scenario.min_net_edge_cents - 1e-9 or raw_c < scenario.min_raw_edge_cents - 1e-9:
            reject = True
        elif secs is not None and (secs < scenario.min_seconds_to_close or secs > scenario.max_seconds_to_close):
            reject = True
        elif scenario.allowed_time_to_close_bucket and ttc_bucket(secs) != scenario.allowed_time_to_close_bucket:
            reject = True
        elif c["book_age_ms"] is not None and c["book_age_ms"] > scenario.max_book_age_ms:
            reject = True
        elif c["spread_cents"] is not None and c["spread_cents"] > scenario.max_spread_cents:
            reject = True
        elif c["depth"] is not None and c["depth"] < scenario.min_depth:
            reject = True
        elif scenario.use_deribit_regime_filter and c.get("deribit_regime") == "high":
            reject = True
        if reject:
            win_last_reject[tk] = ts
            continue
        # per-window caps
        if win_entries[tk] >= min(scenario.max_entries_per_window, scenario.max_trades_per_window):
            continue
        if win_entries[tk] >= 1 and not scenario.allow_multiple_entries_same_window:
            continue
        if (win_entries[tk] >= 1 and scenario.require_different_side_for_reentry
                and c["side"] in win_sides[tk]):
            continue
        # cooldowns (per window)
        le = win_last_entry.get(tk)
        if le is not None and ts is not None and (ts - le) / 1000.0 < scenario.cooldown_after_entry_seconds:
            continue
        lr = win_last_reject.get(tk)
        if lr is not None and ts is not None and (ts - lr) / 1000.0 < scenario.cooldown_after_reject_seconds:
            continue
        if day_count[c["day"]] >= scenario.max_daily_trades:
            continue
        accepted.append(_settle(c, fee_model, size))
        win_entries[tk] += 1
        win_last_entry[tk] = ts
        win_sides[tk].add(c["side"])
        day_count[c["day"]] += 1
    st = _trade_stats(accepted)
    nd = st["distinct_days"] or 1
    return FrequencyResult(
        scenario=scenario.name, trades=st["trades"], distinct_windows=st["distinct_windows"],
        distinct_days=st["distinct_days"], trades_per_window=st["trades_per_window"],
        raw_trades_per_day=(st["trades"] / nd), distinct_windows_per_day=(st["distinct_windows"] / nd),
        fraction_same_window=st["fraction_same_window"], net_pnl=st["net_pnl"],
        hit_rate=st["hit_rate"], avg_net_edge_cents=st["avg_net_edge_cents"],
        realized_pnl_per_contract=st["realized_pnl_per_contract"], max_drawdown=st["max_drawdown"],
        params={"min_net_edge_cents": scenario.min_net_edge_cents,
                "max_trades_per_window": scenario.max_trades_per_window,
                "cooldown_after_entry_seconds": scenario.cooldown_after_entry_seconds,
                "min_seconds_to_close": scenario.min_seconds_to_close,
                "max_daily_trades": scenario.max_daily_trades,
                "allow_multiple_entries_same_window": scenario.allow_multiple_entries_same_window})


def build_scenario_grid(cfg: FrequencyConfig, *, max_scenarios: Optional[int] = None) -> list[FrequencyScenario]:
    """Bounded grid over the four primary axes (NOT a full combinatorial explosion).

    Other scenario fields stay at safe defaults. Truncated deterministically to
    ``max_scenarios`` (default from config)."""
    cap = int(max_scenarios if max_scenarios is not None else cfg.default_max_scenarios)
    out: list[FrequencyScenario] = []
    for mne in cfg.min_net_edge_grid_cents:
        for mtw in cfg.max_trades_per_window_grid:
            for cd in cfg.cooldown_grid_seconds:
                for mstc in cfg.min_seconds_to_close_grid:
                    if len(out) >= cap:
                        return out
                    out.append(FrequencyScenario(
                        name=f"edge{mne}c_mtw{mtw}_cd{cd}s_min{mstc}s",
                        min_net_edge_cents=float(mne), max_trades_per_window=int(mtw),
                        max_entries_per_window=int(mtw),
                        allow_multiple_entries_same_window=(int(mtw) > 1),
                        cooldown_after_entry_seconds=float(cd), min_seconds_to_close=float(mstc)))
    return out


# --------------------------------------------------------------------------- #
# Part D — marginal trade curve
# --------------------------------------------------------------------------- #
def marginal_trade_curve(candidates: list[dict], fee_model: KalshiFeeModel, *, size: float = 1.0,
                         top_ns=(5, 10, 20, 50, 100),
                         edge_thresholds_cents=(10, 7, 5, 3, 2, 1)) -> MarginalTradeCurve:
    """Rank candidates by estimated net edge; report cumulative/marginal net P&L for
    top-N and edge-threshold buckets. Finds where marginal trades stop adding value."""
    settled = [_settle(c, fee_model, size) for c in candidates]
    ranked = sorted(settled, key=lambda c: (c["net_edge"] if c["net_edge"] is not None else -9.0),
                    reverse=True)
    buckets: list[MarginalTradeBucket] = []

    def mk(label, sel, cum, inc):
        st = _trade_stats(sel)
        return MarginalTradeBucket(
            label=label, trades=st["trades"], distinct_windows=st["distinct_windows"],
            trades_per_window=st["trades_per_window"], fraction_same_window=st["fraction_same_window"],
            cumulative_net_pnl=round(cum, 6), incremental_net_pnl=(round(inc, 6) if inc is not None else None),
            avg_net_edge_cents=st["avg_net_edge_cents"], realized_pnl_per_contract=st["realized_pnl_per_contract"],
            hit_rate=st["hit_rate"], max_drawdown=st["max_drawdown"])

    prev = 0.0
    for n in top_ns:
        sel = ranked[:n]
        cum = sum(t["net_pnl"] for t in sel)
        buckets.append(mk(f"top_{n}_by_edge", sel, cum, cum - prev))
        prev = cum
    for thr in edge_thresholds_cents:
        sel = [t for t in ranked if (t["net_edge"] or -9.0) * 100.0 >= thr - 1e-9]
        cum = sum(t["net_pnl"] for t in sel)
        buckets.append(mk(f">={thr}c_edge", sel, cum, None))

    # peak of cumulative net P&L as trades are added in rank order
    cum = peak = 0.0
    peak_rank = 0
    for i, t in enumerate(ranked, start=1):
        cum += t["net_pnl"]
        if cum > peak:
            peak, peak_rank = cum, i
    warnings: list[str] = []
    windows = {c["ticker"] for c in ranked}
    if ranked and peak_rank < len(ranked):
        warnings.append(f"cumulative net P&L peaks at rank {peak_rank}/{len(ranked)} — "
                        "trades beyond that reduced net P&L (marginal value turned negative).")
    if ranked and len(windows) and len(ranked) / len(windows) > 2.0:
        warnings.append(f"{len(ranked)} candidates across only {len(windows)} distinct windows "
                        "(trades/window > 2) — raw trade count overstates independent evidence.")
    return MarginalTradeCurve(buckets=buckets, peak_cumulative_net_pnl=round(peak, 6),
                              peak_at_rank=peak_rank, total_candidates=len(ranked),
                              distinct_windows=len(windows), warnings=warnings)


# --------------------------------------------------------------------------- #
# Part E — time-to-close analysis (uses ALL eval rows for reject reasons)
# --------------------------------------------------------------------------- #
def time_to_close_analysis(eval_rows: list[dict], fee_model: KalshiFeeModel, *, size: float = 1.0,
                           min_net_edge_cents: float = 2.0) -> list[TradeFrequencyBucket]:
    params = BacktestParams(size=size, min_net_edge_cents=min_net_edge_cents)
    groups: dict = defaultdict(lambda: {"cand": [], "exec": [], "reasons": Counter(),
                                        "book_invalid": 0, "stale": 0, "n": 0})
    for r in eval_rows:
        b = ttc_bucket(r.get("seconds_to_close"))
        g = groups[b]
        g["n"] += 1
        if not bool(r.get("book_ok")):
            g["book_invalid"] += 1
        if r.get("coinbase_stale") and r.get("binance_stale"):
            g["stale"] += 1
        p = _prob_for(r)
        dec = evaluate_row(r, p, params, fee_model)
        if dec["side"] is not None and dec["net_edge"] is not None:
            g["cand"].append(dec)
        if dec["tradeable"] and r.get("label_yes_resolved") is not None:
            fee = fee_model.taker_fee(dec["entry_price"], size)
            s = settle_trade(dec["side"], dec["entry_price"], size, int(r["label_yes_resolved"]), fee)
            g["exec"].append({"ticker": r.get("ticker"), "as_of_ts_ms": r.get("as_of_ts_ms"),
                              "day": _utc_day(r.get("as_of_ts_ms")), "net_edge": dec["net_edge"],
                              "net_pnl": s["net_pnl"], "win": s["win"], "fee_total": fee})
        elif not dec["tradeable"] and dec["reasons"]:
            g["reasons"][dec["reasons"][-1]] += 1
    out: list[TradeFrequencyBucket] = []
    for name, _lo, _hi in TTC_BUCKETS:
        g = groups.get(name)
        if not g:
            continue
        ex = g["exec"]
        st = _trade_stats(ex) if ex else None
        out.append(TradeFrequencyBucket(
            bucket=name, candidates=len(g["cand"]), executed=len(ex),
            distinct_windows=(st["distinct_windows"] if st else 0),
            net_pnl=(st["net_pnl"] if st else 0.0), hit_rate=(st["hit_rate"] if st else None),
            mean_net_edge_cents=(sum((c["net_edge"] or 0) for c in g["cand"]) / len(g["cand"]) * 100.0
                                 if g["cand"] else None),
            avg_fee=(sum(e["fee_total"] for e in ex) / len(ex)) if ex else None,
            book_invalid_rate=(g["book_invalid"] / g["n"]) if g["n"] else None,
            source_stale_rate=(g["stale"] / g["n"]) if g["n"] else None,
            top_reject_reasons=dict(g["reasons"].most_common(4))))
    return out


# --------------------------------------------------------------------------- #
# Part F — within-window overtrading analysis
# --------------------------------------------------------------------------- #
def within_window_analysis(candidates: list[dict], fee_model: KalshiFeeModel, *, size: float = 1.0,
                           min_net_edge_cents: float = 2.0) -> dict:
    """Compare max 1/2/3/unlimited entries-per-window policies + concentration warnings."""
    elig = [c for c in candidates if (c["net_edge"] or -9.0) * 100.0 >= min_net_edge_cents - 1e-9]
    by_window: dict = defaultdict(list)
    for c in elig:
        by_window[c["ticker"]].append(c)

    def policy(max_entries):
        sc = FrequencyScenario(name=f"max{max_entries}", min_net_edge_cents=min_net_edge_cents,
                               max_trades_per_window=max_entries, max_entries_per_window=max_entries,
                               allow_multiple_entries_same_window=(max_entries > 1))
        r = simulate_frequency_policy(candidates, sc, fee_model, size=size)
        return {"trades": r.trades, "distinct_windows": r.distinct_windows,
                "net_pnl": r.net_pnl, "hit_rate": r.hit_rate,
                "trades_per_window": r.trades_per_window}

    policies = {f"max_{k}_entries_per_window": policy(k) for k in (1, 2, 3)}
    policies["unlimited_entries_per_window"] = policy(10**6)

    n_trades = len(elig)
    windows = sorted(by_window.items(), key=lambda kv: len(kv[1]), reverse=True)
    top10 = max(1, len(windows) // 10)
    trades_in_top = sum(len(v) for _k, v in windows[:top10])
    warnings: list[OvertradingWarning] = []
    if n_trades and len(by_window) and n_trades / len(by_window) > 2.0:
        warnings.append(OvertradingWarning(
            "CONCENTRATION",
            f"{n_trades} eligible candidates across {len(by_window)} windows "
            f"(={n_trades / len(by_window):.1f}/window); same-window trades are correlated "
            "(one label per window) — not independent samples."))
    if n_trades and trades_in_top / n_trades > 0.5 and len(windows) > 1:
        warnings.append(OvertradingWarning(
            "TOP_WINDOW_DOMINANCE",
            f"top {top10} window(s) hold {trades_in_top}/{n_trades} candidates "
            f"({trades_in_top / n_trades:.0%}) — performance may hinge on a few windows."))
    base = policies["max_1_entries_per_window"]["net_pnl"]
    unl = policies["unlimited_entries_per_window"]["net_pnl"]
    if unl <= base + 1e-9:
        warnings.append(OvertradingWarning(
            "EXTRA_TRADES_NO_GAIN",
            f"unlimited entries/window net P&L ({unl}) did not beat max-1/window ({base}); "
            "extra within-window trades add risk without net benefit.", "info"))
    return {"policies": policies, "distinct_windows": len(by_window), "eligible_candidates": n_trades,
            "warnings": [w.__dict__ for w in warnings]}


# --------------------------------------------------------------------------- #
# Part G — frequency vs calibration
# --------------------------------------------------------------------------- #
def calibration_buckets(candidates: list[dict], fee_model: KalshiFeeModel, *, size: float = 1.0) -> list[dict]:
    settled = [_settle(c, fee_model, size) for c in candidates]
    groups: dict = defaultdict(list)
    for t in settled:
        groups[prob_bucket(t.get("p_yes"))].append(t)
    out = []
    for b in [f"{int(lo*100)}-{int(hi*100) if hi <= 1 else 100}%" for lo, hi in PROB_BUCKETS]:
        ts = groups.get(b)
        if not ts:
            continue
        n = len(ts)
        realized_yes = sum(t["label_yes"] for t in ts) / n
        mean_p = sum((t["p_yes"] or 0) for t in ts) / n
        brier = sum((( t["p_yes"] or 0) - t["label_yes"]) ** 2 for t in ts) / n
        out.append({
            "prob_bucket": b, "candidates": n, "mean_predicted_p": round(mean_p, 4),
            "realized_yes_rate": round(realized_yes, 4), "calibration_gap": round(mean_p - realized_yes, 4),
            "brier_contribution": round(brier, 6),
            "net_pnl": round(sum(t["net_pnl"] for t in ts), 6),
            "avg_net_edge_cents": round(sum((t["net_edge"] or 0) for t in ts) / n * 100.0, 3),
            "avg_market_price": round(sum((t["entry_price"] or 0) for t in ts) / n, 4),
        })
    return out
