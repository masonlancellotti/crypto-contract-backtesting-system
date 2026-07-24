"""Manifest-based PAPER / SHADOW runtime — never newest-by-mtime, never live.

The model + calibrator are loaded ONLY from the explicit paper-promotion manifest
(``paper_promotion.load_active_promotion``), with SHA + is_promoted + non-diagnostic
+ calibrated re-verified. No staged artifact and no "newest .pkl by mtime" is ever
used for runtime decisions.

Three modes (``config.model_runtime_mode``), live is impossible in all:
  - disabled : no model-driven paper candidates (status/inspection only).
  - shadow   : score + run policy + edge policy, write SHADOW_DECISION rows.
               NEVER emits PAPER_CANDIDATE, NEVER paper-fills.
  - paper    : may emit PAPER_CANDIDATE (and simulate paper fills) only when the
               strict paper policy AND the confidence-aware edge policy AND the
               freshness/depth/time/cooldown/daily-cap/per-window gates all pass.

``live_submission_allowed`` is always False.
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Callable, Optional

from .book_freshness import effective_book_age
from .calibrate import Calibrator
from .edge_policy import EdgePolicyConfig, EdgeInputs, evaluate_edge
from .executable_backtest import predict_from_artifact
from .fees import KalshiFeeModel
from .freshness import paper_candidate_freshness
from .model_dataset import build_model_dataset
from .paper import PAPER_CANDIDATE, REJECTED, WATCH, decision_window_skip_reason
from .paper_promotion import load_active_promotion
from .policy import (
    CalibrationValidity, ExecutablePrices, ModelValidity, PolicyInput,
    SourceFreshness, evaluate_policy,
)
from .policy_runtime import assess_backtest_validity
from ...timeutils import now_ms
from .uncertainty import build_calibration_buckets

SHADOW_DECISION = "SHADOW_DECISION"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


# --------------------------------------------------------------------------- #
# Load + validity (from the promotion manifest ONLY)
# --------------------------------------------------------------------------- #
def load_runtime(config, *, series: str = "KXBTC15M") -> dict:
    """Load the promoted paper model/calibrator from the manifest. Never mtime."""
    promo = load_active_promotion(config, series=series)
    if not promo.get("valid"):
        return {"valid": False, "blockers": promo.get("blockers", ["NO_PROMOTED_PAPER_MODEL"]),
                "manifest": promo.get("manifest"), "promo": promo}
    return {"valid": True, "blockers": [], "manifest": promo["manifest"], "promo": promo,
            "model_artifact": promo["model_artifact"], "calibrator_artifact": promo["calibrator_artifact"],
            "model_path": promo["model_path"], "calibrator_path": promo["calibrator_path"]}


def _validity_from_promotion(promo: dict, config) -> tuple:
    """Build (model, calibration, backtest) validity from the PROMOTED artifacts."""
    m = promo.get("model_artifact") or {}
    c = promo.get("calibrator_artifact") or {}
    mv = ModelValidity(
        exists=bool(promo.get("model_artifact")),
        trained=bool(m.get("model") is not None or m.get("sklearn_pipeline") is not None or m.get("model_backend")),
        diagnostic_only=bool(m.get("is_diagnostic") or m.get("tradability") == "NON_TRADABLE_DIAGNOSTIC_ONLY"),
        tradable_stamp=bool(m.get("tradable")), version=m.get("model_name"),
        artifact_path=promo.get("model_path"), feature_schema_version=m.get("model_schema_version"))
    cv = CalibrationValidity(
        exists=bool(promo.get("calibrator_artifact")),
        valid=bool(c.get("calibration_status") == "calibrated" and not c.get("NON_TRADABLE_DIAGNOSTIC_ONLY")),
        diagnostic_only=bool(c.get("NON_TRADABLE_DIAGNOSTIC_ONLY", True)), version=promo.get("calibrator_path"))
    bv = assess_backtest_validity(config)
    return mv, cv, bv


# --------------------------------------------------------------------------- #
# Scoring (promoted model + calibrator)
# --------------------------------------------------------------------------- #
def _score(config, rows, model_art, cal_art):
    """Return (raw_probs, calibrated_probs) using the PROMOTED model + calibrator."""
    idx = list(range(len(rows)))
    if not rows or model_art is None:
        return [None] * len(rows), [None] * len(rows)
    try:
        raw = predict_from_artifact(model_art, rows, idx)
    except Exception:  # noqa: BLE001
        return [None] * len(rows), [None] * len(rows)
    cal = list(raw)
    if cal_art is not None:
        try:
            cobj = Calibrator.from_dict(cal_art.get("calibrator", {}))
            cal = cobj.transform(raw)
        except Exception:  # noqa: BLE001
            cal = list(raw)
    return raw, cal


def _edge_inputs(row, buckets) -> EdgeInputs:
    p = row.get("calibrated_probability_yes")
    ya, na = row.get("yes_ask"), row.get("no_ask")
    ens = {}
    if p is not None:
        ens["model"] = p
        if ya is not None and na is not None and (ya + na) > 0:
            ens["market_implied"] = max(0.0, min(1.0, ya / (ya + na)))
    spread = max(row.get("yes_spread") or 0.0, row.get("no_spread") or 0.0)
    return EdgeInputs(
        p_yes_hat=p, p_yes_lower=row.get("model_p_yes_lower"), p_yes_upper=row.get("model_p_yes_upper"),
        yes_ask=ya, no_ask=na, yes_ask_size=row.get("yes_ask_size"), no_ask_size=row.get("no_ask_size"),
        seconds_to_close=row.get("seconds_to_close"), spread_cents=(spread * 100.0) if spread else None,
        book_age_ms=row.get("book_age_ms"), underlying_age_ms=row.get("underlying_age_ms"),
        coinbase_stale=bool(row.get("coinbase_stale")), binance_stale=bool(row.get("binance_stale")),
        deribit_regime=row.get("deribit_regime"), sigma_per_sqrt_s=row.get("spot_sigma_per_sqrt_s"),
        overtrading=False, calibration_buckets=buckets, ensemble_probs=ens,
        model_calibrated=True, model_tradable=True, backtest_valid=True)


# --------------------------------------------------------------------------- #
# Core evaluation (dual-gated: paper policy AND edge policy)
# --------------------------------------------------------------------------- #
def evaluate_paper_rows(config, *, series: str = "KXBTC15M", mode: Optional[str] = None,
                        limit: int = 20, enforce_feature_row_age: bool = False,
                        feature_row_max_age_ms: Optional[int] = None) -> dict:
    """Score recent rows with the promoted artifacts and dual-gate them.

    Returns decisions + a summary. In ``shadow`` mode the decision_state is forced to
    SHADOW_DECISION (never PAPER_CANDIDATE); in ``paper`` mode PAPER_CANDIDATE is only
    possible when BOTH the paper policy and the edge policy pass plus rate gates.

    The wall-clock age of each evaluated feature row (now - as_of) is computed + reported
    so it is obvious when the runtime is reading STALE stored rows (e.g. 14m-old features
    batched per cycle). With ``enforce_feature_row_age`` a would-be candidate on a row older
    than ``feature_row_max_age_ms`` (default ``config.freshness.feature_row_max_age_ms``) is
    REJECTED (FEATURE_ROW_STALE) — stale data never trades.
    """
    mode = (mode or config.model_runtime_mode or "disabled").lower()
    prep = _prepare_runtime(config, series=series, mode=mode)
    if prep["status"] != "OK":
        return prep["base"]
    rows = prep["dataset_rows"]
    eval_rows = rows[-limit:] if (limit and limit > 0) else rows
    ftr_thr = int(feature_row_max_age_ms if feature_row_max_age_ms is not None
                  else config.freshness.feature_row_max_age_ms)
    decisions, states, feat_ages = _gate_rows(
        prep, eval_rows, mode=mode, series=series, now=now_ms(),
        trade_state=_new_trade_state(config),
        enforce_feature_row_age=enforce_feature_row_age, feature_row_max_age_ms=ftr_thr)
    return _summarize_eval(prep["base"], prep, decisions, states, feat_ages,
                           enforce_feature_row_age=enforce_feature_row_age, ftr_thr=ftr_thr,
                           n_rows=len(eval_rows))


def _prepare_runtime(config, *, series, mode) -> dict:
    """Load the promoted runtime + build the dataset/calibration-buckets ONCE.

    Returns a context with ``status`` (OK / RUNTIME_DISABLED / NO_PROMOTED_PAPER_MODEL),
    ``base``, and (on OK) everything the gating needs. The expensive build_model_dataset +
    bucket build happen here ONCE per run — so the live loop can re-evaluate cheaply."""
    pc = config.paper_policy
    edge_cfg = EdgePolicyConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)
    rt = load_runtime(config, series=series)
    base = {"series": series, "runtime_mode": mode, "live_submission_allowed": False,
            "manifest_valid": rt["valid"], "blockers": list(rt["blockers"]),
            "decisions": [], "decisions_by_state": {}, "paper_candidates": 0,
            "shadow_decisions": 0, "manifest_path": None}
    if mode == "disabled":
        base["status"] = "RUNTIME_DISABLED"
        base["note"] = "model_runtime_mode=disabled: no model-driven paper candidates."
        return {"status": "RUNTIME_DISABLED", "base": base}
    if not rt["valid"]:
        base["status"] = "NO_PROMOTED_PAPER_MODEL"
        return {"status": "NO_PROMOTED_PAPER_MODEL", "base": base}
    manifest = rt["manifest"]
    base["manifest_path"] = rt["promo"].get("manifest_path")
    model_art, cal_art = rt["model_artifact"], rt["calibrator_artifact"]
    mv, cv, bv = _validity_from_promotion(rt["promo"], config)

    import dataclasses
    cpc = manifest.get("conservative_policy_config", {})
    pc_eff = dataclasses.replace(
        pc, enabled=True,
        min_net_edge_cents=float(cpc.get("min_net_edge_cents", pc.min_net_edge_cents)),
        min_raw_edge_cents=float(cpc.get("min_raw_edge_cents", pc.min_raw_edge_cents)),
        max_trades_per_window=int(cpc.get("max_trades_per_window", pc.max_trades_per_window)),
        max_book_age_ms=int(cpc.get("max_book_age_ms", pc.max_book_age_ms)),
        max_underlying_age_ms=int(cpc.get("max_underlying_age_ms", pc.max_underlying_age_ms)),
        min_seconds_to_close=int(cpc.get("min_seconds_to_close", pc.min_seconds_to_close)),
        max_spread_cents=float(cpc.get("max_spread_cents", pc.max_spread_cents)),
        min_top_depth_contracts=float(cpc.get("min_depth_contracts", pc.min_top_depth_contracts)))
    edge_cfg = dataclasses.replace(
        edge_cfg, enabled=True,
        min_raw_edge_cents=float(cpc.get("min_raw_edge_cents", edge_cfg.min_raw_edge_cents)),
        min_final_edge_cents=float(cpc.get("min_final_edge_cents", edge_cfg.min_final_edge_cents)),
        require_confidence_bounds=bool(cpc.get("require_confidence_bounds", edge_cfg.require_confidence_bounds)))

    ds = build_model_dataset(config, series=series)
    rows = sorted(ds["rows"], key=lambda r: (r.get("as_of_ts_ms") or 0))
    raw, cal = _score(config, rows, model_art, cal_art)
    labelled_p, labelled_y = [], []
    for j, r in enumerate(rows):
        r["model_probability_yes"] = raw[j]
        r["calibrated_probability_yes"] = cal[j]
        if r.get("label_yes_resolved") is not None and cal[j] is not None:
            labelled_p.append(cal[j]); labelled_y.append(int(r["label_yes_resolved"]))
    buckets = build_calibration_buckets(labelled_y, labelled_p) if labelled_p else []
    return {"status": "OK", "base": base, "mode": mode, "rt": rt, "manifest": manifest,
            "model_art": model_art, "cal_art": cal_art, "mv": mv, "cv": cv, "bv": bv,
            "pc_eff": pc_eff, "edge_cfg": edge_cfg, "fee_model": fee_model, "buckets": buckets,
            "dataset_rows": rows, "fcfg": config.freshness,
            "edge_required": bool(pc.require_edge_policy), "edge_available": bool(edge_cfg.enabled)}


def _summarize_eval(base, prep, decisions, states, feat_ages, *, enforce_feature_row_age,
                    ftr_thr, n_rows) -> dict:
    base["status"] = "OK"
    base["decisions"] = decisions
    base["decisions_by_state"] = dict(states)
    base["paper_candidates"] = states.get(PAPER_CANDIDATE, 0)
    base["shadow_decisions"] = states.get(SHADOW_DECISION, 0)
    base["n_rows_evaluated"] = n_rows
    base["edge_policy_required"] = prep["edge_required"]
    base["calibration_buckets"] = len(prep["buckets"])
    base["freshness_stale_rows"] = sum(1 for d in decisions if d.get("freshness_ok") is False)
    base["book_stale_rows"] = sum(1 for d in decisions if d.get("book_decision_stale") is True)
    base["underlying_stale_rows"] = sum(
        1 for d in decisions if d.get("underlying_decision_stale") is True)
    base["deribit_stale_rows"] = sum(
        1 for d in decisions
        if d.get("deribit_stale") is True or "STALE_DERIBIT" in (d.get("reason_codes") or []))
    base["freshness_fallback_used_rows"] = sum(1 for d in decisions if d.get("underlying_fallback_used"))
    base["feature_row_stale_rows"] = sum(1 for d in decisions if "FEATURE_ROW_STALE" in (d.get("reason_codes") or []))
    base["freshest_feature_row_age_ms"] = (min(feat_ages) if feat_ages else None)
    base["stalest_feature_row_age_ms"] = (max(feat_ages) if feat_ages else None)
    base["enforce_feature_row_age"] = bool(enforce_feature_row_age)
    base["feature_row_max_age_ms"] = ftr_thr
    base["model_path"] = prep["rt"]["model_path"]
    base["calibrator_path"] = prep["rt"]["calibrator_path"]
    return base


def _new_trade_state(config) -> dict:
    """Mutable cross-iteration trade state (cooldown / per-window / daily caps)."""
    pc = config.paper_policy
    return {"trades_window": Counter(), "trades_today": 0, "last_entry_ms": None,
            "cooldown_ms": int(getattr(pc, "entry_cooldown_seconds", 30)) * 1000,
            "max_daily": int(getattr(pc, "max_daily_trades", 10))}


def _gate_rows(prep, rows, *, mode, series, now, trade_state, enforce_feature_row_age,
               feature_row_max_age_ms):
    """Score-aware dual-gate over ``rows`` (already carrying calibrated probs). Returns
    (decisions, states, feat_ages). ``trade_state`` persists across live-loop iterations so
    cooldown / per-window / daily caps hold over time. Identical gating to the single pass."""
    pc_eff, edge_cfg, fee_model = prep["pc_eff"], prep["edge_cfg"], prep["fee_model"]
    buckets, mv, cv, bv = prep["buckets"], prep["mv"], prep["cv"], prep["bv"]
    manifest, rt, fcfg = prep["manifest"], prep["rt"], prep["fcfg"]
    edge_required, edge_available = prep["edge_required"], prep["edge_available"]
    tw = trade_state["trades_window"]
    cooldown_ms, max_daily = trade_state["cooldown_ms"], trade_state["max_daily"]
    ftr_thr = int(feature_row_max_age_ms)
    states: Counter = Counter()
    decisions: list[dict] = []
    feat_ages: list[int] = []
    for r in rows:
        pi = _policy_input(r, series=series, mv=mv, cv=cv, bv=bv)
        pdec = evaluate_policy(pi, pc_eff, fee_model=fee_model)
        edge = evaluate_edge(_edge_inputs(r, buckets), edge_cfg, fee_model)
        state = pdec.decision_state
        reasons = list(pdec.reason_codes)

        as_of = r.get("as_of_ts_ms")
        feat_age = (now - int(as_of)) if as_of is not None else None
        if feat_age is not None:
            feat_ages.append(feat_age)
        feature_row_stale = bool(enforce_feature_row_age and feat_age is not None and feat_age > ftr_thr)

        # ----- DECISION-FRESHNESS gate (stale data must NEVER become PAPER_CANDIDATE) -----
        fr_gate = paper_candidate_freshness(
            book_age_ms=r.get("book_age_ms"), coinbase_age_ms=r.get("coinbase_feed_age_ms"),
            binance_age_ms=r.get("binance_feed_age_ms"), fcfg=fcfg, feature_row_age_ms=None)
        if state == PAPER_CANDIDATE and not fr_gate["ok"]:
            state, reasons = REJECTED, reasons + list(fr_gate["reasons"])
        if state == PAPER_CANDIDATE and feature_row_stale and "FEATURE_ROW_STALE" not in reasons:
            state, reasons = REJECTED, reasons + ["FEATURE_ROW_STALE"]

        # ----- edge policy REQUIRED for a paper candidate -----
        if state == PAPER_CANDIDATE:
            if edge_required and not edge_available:
                state, reasons = REJECTED, reasons + ["EDGE_POLICY_MISSING"]
            elif edge.state != "EDGE_OK":
                state, reasons = WATCH, reasons + [f"EDGE_POLICY_BLOCKED:{edge.state}"] + edge.reason_codes[:2]
            elif edge.side and pdec.selected_side and edge.side != pdec.selected_side:
                state, reasons = WATCH, reasons + ["EDGE_POLICY_SIDE_DISAGREE"]

        # ----- rate gates (cooldown + daily cap + per-window) -----
        if state == PAPER_CANDIDATE:
            tk = r.get("ticker")
            if tw[tk] >= pc_eff.max_trades_per_window:
                state, reasons = WATCH, reasons + ["MAX_TRADES_PER_WINDOW"]
            elif trade_state["trades_today"] >= max_daily:
                state, reasons = WATCH, reasons + ["MAX_DAILY_TRADES"]
            elif (trade_state["last_entry_ms"] is not None and as_of is not None
                  and (as_of - trade_state["last_entry_ms"]) < cooldown_ms):
                state, reasons = WATCH, reasons + ["ENTRY_COOLDOWN_ACTIVE"]

        # ----- shadow mode: never a candidate, never a fill -----
        if mode == "shadow" and state == PAPER_CANDIDATE:
            reasons = ["SHADOW_WOULD_BE_PAPER_CANDIDATE"] + reasons
            state = SHADOW_DECISION
        elif mode == "shadow":
            state = SHADOW_DECISION if state in (WATCH, REJECTED) else state

        if mode == "paper" and state == PAPER_CANDIDATE:
            tw[r.get("ticker")] += 1
            trade_state["trades_today"] += 1
            trade_state["last_entry_ms"] = as_of

        states[state] += 1
        decisions.append(_record(r, pdec, edge, manifest, rt, mode, state, reasons, fr_gate,
                                 feature_row_age_ms=feat_age))
    return decisions, states, feat_ages


# --------------------------------------------------------------------------- #
# Live shadow/paper LOOP — samples FRESH current rows for a wall-clock duration
# --------------------------------------------------------------------------- #
def _live_row(fr: dict) -> dict:
    """Map a raw recorded feature row -> the runtime row shape (live; no label yet)."""
    r = dict(fr)
    r["ticker"] = fr.get("market_ticker")
    r["as_of_ts_ms"] = fr.get("as_of_ms")
    r["market_close_ts_ms"] = fr.get("close_ms")
    r["market_open_ts_ms"] = fr.get("window_start_ms")
    book_age = effective_book_age(fr, as_of_ms=fr.get("as_of_ms"))
    r["book_age_ms"] = book_age.get("book_age_ms")
    r["book_age_basis"] = book_age.get("book_age_basis")
    r["book_age_method"] = book_age.get("book_age_method")
    r["book_age_source"] = book_age.get("book_age_source")
    r["book_age_confidence"] = book_age.get("book_age_confidence")
    r["book_recv_ms"] = book_age.get("book_recv_ms")
    r["book_source_ts_ms"] = book_age.get("book_source_ts_ms")
    ages = [a for a in (fr.get("coinbase_feed_age_ms"), fr.get("binance_feed_age_ms")) if a is not None]
    r["underlying_age_ms"] = max(ages) if ages else None
    r["label_yes_resolved"] = None     # live / in-window: not settled yet
    return r


def _read_tail_lines(path, max_lines: int, *, max_bytes: int = 12_000_000,
                     chunk: int = 262_144) -> list[str]:
    """Return up to the last ``max_lines`` non-empty lines of ``path`` (chronological order),
    reading at most ``max_bytes`` from the END of the file. Avoids scanning the whole (often
    50-200MB) feature file on every poll. A partial leading line is dropped."""
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size <= 0:
        return []
    want = min(int(size), int(max_bytes))
    try:
        with path.open("rb") as fh:
            fh.seek(size - want)
            data = fh.read(want)
    except OSError:
        return []
    if want < size:                       # started mid-line -> drop the partial first line
        nl = data.find(b"\n")
        data = data[nl + 1:] if nl != -1 else b""
    raw = [ln for ln in data.split(b"\n") if ln.strip()]
    if len(raw) > max_lines:
        raw = raw[-max_lines:]
    out: list[str] = []
    for ln in raw:
        try:
            out.append(ln.decode("utf-8"))
        except UnicodeDecodeError:
            continue
    return out


def _latest_orderbook_rows_by_ticker(config, *, lines: int) -> dict[str, list[dict]]:
    d = config.data_path() / "normalized"
    if not d.exists():
        return {}
    files = sorted(d.glob("kalshi_orderbook*.jsonl"))
    if not files:
        return {}
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for ln in _read_tail_lines(files[-1], max(1, int(lines))):
        try:
            row = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        ev = row.get("event") if isinstance(row.get("event"), dict) else row
        tk = ev.get("market_ticker") or ev.get("ticker")
        if not tk or ev.get("recv_ms") is None:
            continue
        by_ticker[tk].append(ev)
    for tk in list(by_ticker):
        by_ticker[tk].sort(key=lambda ev: int(ev.get("recv_ms") or 0))
    return dict(by_ticker)


def _attach_normalized_book_timestamp(fr: dict, books_by_ticker: dict[str, list[dict]]) -> dict:
    """Backfill book timestamp provenance from normalized rows when old feature rows lack it.

    This is only used for live shadow/paper row selection. It never uses future
    data: the chosen normalized orderbook row must have ``recv_ms <= as_of_ms``.
    """
    if any(fr.get(k) is not None for k in (
        "book_age_ms", "quote_age_ms", "recv_ms", "book_recv_ms", "source_ts_ms", "book_source_ts_ms"
    )):
        return fr
    tk = fr.get("market_ticker")
    as_of = fr.get("as_of_ms")
    if not tk or as_of is None:
        return fr
    try:
        as_of_i = int(as_of)
    except (TypeError, ValueError):
        return fr
    best = None
    for ev in books_by_ticker.get(tk, []):
        try:
            recv = int(ev.get("recv_ms"))
        except (TypeError, ValueError):
            continue
        if recv <= as_of_i:
            best = ev
        else:
            break
    if best is None:
        return fr
    out = dict(fr)
    out["recv_ms"] = best.get("recv_ms")
    out["source_ts_ms"] = best.get("source_ts_ms")
    out["quote_age_ms"] = best.get("quote_age_ms")
    out["book_recv_ms"] = best.get("recv_ms")
    out["book_source_ts_ms"] = best.get("source_ts_ms")
    out["book_timestamp_joined_from_normalized"] = True
    return out


def latest_feature_rows(config, *, series: str = "KXBTC15M", lines: int = 4000) -> list[dict]:
    """Tail-read the newest recorded feature file -> the FRESHEST snapshot per discovered market.

    This is the CURRENT data path. The collector records a row for EVERY discovered market
    (open / upcoming / closed) on every poll, so the raw tail is dominated by stale repeat
    snapshots of the same tickers. We scan the last ``lines`` rows and keep only the LATEST
    (max ``as_of_ms``) row per ``market_ticker`` — the snapshot a live decision would act on.
    These are still *collection* rows (one per market); callers MUST filter to executable active
    rows via ``_decision_eligibility`` before scoring. ``lines`` must be wide enough to span the
    full set of discovered markets across a couple of recent polls.

    When ``config.feature_source == 'hires'`` the freshest rows come from the
    sub-second WS joined snapshots instead (same feature-row schema), so the paper /
    decision path can run on second-level data. REST is the default and unchanged."""
    from .feature_source import HIRES, latest_hires_feature_rows, normalize_source
    if normalize_source(None, config=config) == HIRES:
        return latest_hires_feature_rows(config, series=series)
    d = config.data_path() / "features"
    if not d.exists():
        return []
    files = sorted(d.glob("kalshi_feature_rows*.jsonl"))
    if not files:
        return []
    latest_by_ticker: dict = {}
    for ln in _read_tail_lines(files[-1], max(1, int(lines))):
        try:
            fr = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        tk = fr.get("market_ticker")
        as_of = fr.get("as_of_ms")
        prev = latest_by_ticker.get(tk)
        if prev is None:
            latest_by_ticker[tk] = fr
        else:
            pa = prev.get("as_of_ms")
            if as_of is not None and (pa is None or as_of >= pa):
                latest_by_ticker[tk] = fr
    books_by_ticker = _latest_orderbook_rows_by_ticker(config, lines=lines)
    return [_live_row(_attach_normalized_book_timestamp(fr, books_by_ticker))
            for fr in latest_by_ticker.values()]


# Pre-scoring rejection reasons (separate COLLECTION rows from executable DECISION rows).
SELECT_REASONS = ("MARKET_CLOSED", "MARKET_NOT_OPEN", "OUTSIDE_DECISION_WINDOW",
                  "TOO_FAR_FROM_CLOSE", "TOO_CLOSE_TO_CLOSE", "MISSING_BOOK",
                  "MISSING_START_REFERENCE", "INSUFFICIENT_DEPTH", "FEATURE_ROW_STALE")


def _decision_eligibility(row: dict, *, pc, market_duration_seconds: int,
                          feature_row_max_age_ms: int, now: int) -> tuple:
    """Is ``row`` a valid shadow/paper DECISION target *right now*?

    Separates COLLECTION rows (upcoming / closed / no-book / illiquid / stale) from executable
    ACTIVE rows. Uses the SAME policy thresholds as ``evaluate_policy`` — it NEVER weakens or
    loosens them; it only declines to score rows the policy would hard-reject anyway, so the
    shadow loop scores real active in-window decisions instead of collection noise.

    Returns ``(eligible, reasons, flags)``. ``reasons`` lists every applicable pre-scoring
    reject reason (``reasons[0]`` is the primary one); empty => eligible. ``flags`` carries the
    funnel classification (active_window / book_backed / start_reference / feature_row_age_ms).

    The active-window test uses the CURRENT time-to-close (``market_close_ts_ms - now``), NOT the
    recorded ``seconds_to_close`` (which is point-in-time at ``as_of``): a stale snapshot that was
    recorded with status='active' and seconds_to_close=53 is, an hour later, a CLOSED market — so
    it must be judged against the wall clock, not its recording time."""
    reasons: list[str] = []
    # CURRENT time-to-close from the wall clock (fall back to recorded secs only if no close ts).
    close_ms = row.get("market_close_ts_ms")
    recorded_secs = row.get("seconds_to_close")
    secs = ((int(close_ms) - int(now)) / 1000.0) if close_ms is not None else recorded_secs
    # 1) current ACTIVE in-window market (status + 0 < current_seconds_to_close <= market_duration)
    probe = {"status": row.get("status"), "accepting_orders": row.get("accepting_orders"),
             "seconds_to_close": secs}
    skip = decision_window_skip_reason(probe, market_duration_seconds=int(market_duration_seconds))
    active_window = skip is None
    if skip is not None:
        reasons.append(skip)
    # 2) within the policy time window (do NOT loosen min/max seconds-to-close)
    if active_window and secs is not None:
        if secs > pc.max_seconds_to_close:
            reasons.append("TOO_FAR_FROM_CLOSE")
        elif secs < pc.min_seconds_to_close:
            reasons.append("TOO_CLOSE_TO_CLOSE")
    # 3) executable book (yes/no ask present)
    book_backed = bool(row.get("book_ok")) and row.get("yes_ask") is not None and row.get("no_ask") is not None
    if not book_backed:
        reasons.append("MISSING_BOOK")
    # 4) start reference / line
    start_reference = row.get("reference_start_price") is not None
    if not start_reference:
        reasons.append("MISSING_START_REFERENCE")
    # 5) sufficient depth (same metric as the policy: yes_ask_size + no_ask_size)
    yes_depth = row.get("yes_ask_size")
    no_depth = row.get("no_ask_size")
    depth_values_present = yes_depth is not None and no_depth is not None
    depth = (yes_depth or 0.0) + (no_depth or 0.0)
    executable_depth = bool(depth_values_present and depth >= pc.min_top_depth_contracts)
    depth_missing_reason = None
    if not depth_values_present:
        depth_missing_reason = "MISSING_DEPTH"
    elif depth < pc.min_top_depth_contracts:
        depth_missing_reason = "INSUFFICIENT_DEPTH"
    if not executable_depth:
        reasons.append("INSUFFICIENT_DEPTH")
    # 6) feature row fresh enough (wall-clock age of the stored row vs threshold)
    as_of = row.get("as_of_ts_ms")
    feat_age = (now - int(as_of)) if as_of is not None else None
    if feat_age is None or feat_age > int(feature_row_max_age_ms):
        reasons.append("FEATURE_ROW_STALE")
    flags = {"active_window": active_window, "book_backed": book_backed,
             "start_reference": start_reference,
             "reference_missing_reason": row.get("reference_missing_reason") or "START_REFERENCE_MISSING",
             "executable_depth": executable_depth, "depth_missing_reason": depth_missing_reason,
             "feature_row_age_ms": feat_age}
    return (not reasons), reasons, flags


def _empty_selection() -> dict:
    return {"rows_read": 0, "rows_eligible_for_scoring": 0, "executable_rows": 0,
            "active_window_rows": 0, "book_backed_rows": 0, "start_reference_rows": 0,
            "rows_with_start_reference": 0, "rows_missing_start_reference_by_reason": {},
            "rows_with_executable_depth": 0, "rows_missing_depth_by_reason": {},
            "rejected_before_scoring": 0, "rejected_before_scoring_by_reason": {}}


def run_live_shadow(config, *, series: str = "KXBTC15M", minutes: float = 1.0,
                    mode: str = "shadow", poll_interval: float = 5.0, limit: int = 25,
                    scan_lines: int = 4000, max_iterations: Optional[int] = None,
                    sleep: Callable[[float], None] = time.sleep,
                    monotonic: Callable[[], float] = time.monotonic, now_fn: Callable[[], int] = now_ms,
                    feature_row_max_age_ms: Optional[int] = None,
                    on_decisions: Optional[Callable[[list], None]] = None,
                    abort_check: Optional[Callable[[list], Optional[str]]] = None) -> dict:
    """Run a CONTINUOUS shadow/paper loop for ~``minutes`` wall-clock, re-sampling the latest
    recorded feature rows each ``poll_interval`` and evaluating only NEW (ticker, as_of) rows.

    ROW SELECTION: the collector records a row for every discovered market (open / upcoming /
    closed), so the raw tail is mostly COLLECTION noise. Each poll we tail ``scan_lines`` rows,
    keep the new ones, and run ``_decision_eligibility`` to keep ONLY executable active rows
    (current market, in policy time window, book + start-reference + depth, fresh). Only those
    are scored/gated; everything else is counted (per reason) but never scored. Thresholds are
    the policy's own — never weakened. ``limit`` caps eligible rows scored per poll.

    SHADOW never emits a candidate or fills. The clock + sleep are injectable for tests.
    live_submission_allowed is always False."""
    mode = (mode or "shadow").lower()
    eff = mode if mode in ("shadow", "paper") else "shadow"
    prep = _prepare_runtime(config, series=series, mode=eff)
    base = prep["base"]
    base.update(live_loop=True, minutes_requested=minutes, poll_interval=poll_interval, iterations=0)
    if prep["status"] != "OK":
        base["status"] = prep["status"]
        base.update(samples=0, elapsed_s=0.0, abort_reason=None, **_empty_selection())
        return base

    fcfg = config.freshness
    ftr_thr = int(feature_row_max_age_ms if feature_row_max_age_ms is not None
                  else max(int(fcfg.coinbase_decision_max_age_ms), int(float(poll_interval) * 1000 * 2)))
    md_secs = int(getattr(getattr(config, "low_latency", None), "market_duration_seconds", 900))
    pc_eff = prep["pc_eff"]
    trade_state = _new_trade_state(config)
    all_decisions: list[dict] = []
    states: Counter = Counter()
    feat_ages: list[int] = []
    seen: set = set()
    sel = {"rows_read": 0, "active_window_rows": 0, "book_backed_rows": 0,
           "start_reference_rows": 0, "rows_with_start_reference": 0,
           "missing_start_reference_by_reason": Counter(),
           "rows_with_executable_depth": 0, "missing_depth_by_reason": Counter(),
           "executable_rows": 0, "rejected_before_scoring": 0,
           "rejected_by_reason": Counter()}
    start = monotonic()
    end = start + max(0.0, float(minutes) * 60.0)
    it = 0
    abort_reason = None
    while True:
        it += 1
        now = now_fn()
        # ----- tail the latest collection rows; keep only NEW (ticker, as_of) snapshots -----
        fresh: list[dict] = []
        for r in latest_feature_rows(config, series=series, lines=scan_lines):
            key = (r.get("ticker"), r.get("as_of_ts_ms"))
            if key in seen:
                continue
            seen.add(key)
            fresh.append(r)
        # ----- SELECT executable active DECISION rows (separate from collection noise) -----
        eligible: list[dict] = []
        for r in fresh:
            sel["rows_read"] += 1
            ok, reasons, flags = _decision_eligibility(
                r, pc=pc_eff, market_duration_seconds=md_secs,
                feature_row_max_age_ms=ftr_thr, now=now)
            sel["active_window_rows"] += int(bool(flags["active_window"]))
            sel["book_backed_rows"] += int(bool(flags["book_backed"]))
            sel["start_reference_rows"] += int(bool(flags["start_reference"]))
            sel["rows_with_start_reference"] += int(bool(flags["start_reference"]))
            if not flags["start_reference"]:
                sel["missing_start_reference_by_reason"][flags["reference_missing_reason"]] += 1
            sel["rows_with_executable_depth"] += int(bool(flags["executable_depth"]))
            if not flags["executable_depth"]:
                sel["missing_depth_by_reason"][flags["depth_missing_reason"] or "INSUFFICIENT_DEPTH"] += 1
            if ok:
                sel["executable_rows"] += 1
                eligible.append(r)
            else:
                sel["rejected_before_scoring"] += 1
                for rc in reasons:
                    sel["rejected_by_reason"][rc] += 1
        if limit and limit > 0 and len(eligible) > limit:
            eligible = eligible[-int(limit):]
        # ----- score + dual-gate ONLY the executable active rows -----
        if eligible:
            raw, cal = _score(config, eligible, prep["model_art"], prep["cal_art"])
            for j, r in enumerate(eligible):
                r["model_probability_yes"] = raw[j]
                r["calibrated_probability_yes"] = cal[j]
            d, st, ages = _gate_rows(prep, eligible, mode=eff, series=series, now=now,
                                     trade_state=trade_state, enforce_feature_row_age=True,
                                     feature_row_max_age_ms=ftr_thr)
            all_decisions.extend(d)
            states.update(st)
            feat_ages.extend(ages)
            if on_decisions:
                on_decisions(d)
            if abort_check:
                ar = abort_check(d)
                if ar:
                    abort_reason = ar
                    break
        if max_iterations and it >= max_iterations:
            break
        if monotonic() >= end:
            break
        sleep(max(0.2, min(float(poll_interval), max(0.0, end - monotonic()))))

    out = _summarize_eval(base, prep, all_decisions, states, feat_ages,
                          enforce_feature_row_age=True, ftr_thr=ftr_thr, n_rows=len(all_decisions))
    out.update(live_loop=True, iterations=it, samples=len(all_decisions),
               elapsed_s=round(monotonic() - start, 2), minutes_requested=minutes,
               poll_interval=poll_interval, abort_reason=abort_reason,
               distinct_windows=len({d.get("ticker") for d in all_decisions}),
               rows_read=sel["rows_read"], rows_eligible_for_scoring=sel["executable_rows"],
               executable_rows=sel["executable_rows"], active_window_rows=sel["active_window_rows"],
               book_backed_rows=sel["book_backed_rows"], start_reference_rows=sel["start_reference_rows"],
               rows_with_start_reference=sel["rows_with_start_reference"],
               rows_missing_start_reference_by_reason=dict(
                   sel["missing_start_reference_by_reason"].most_common()),
               rows_with_executable_depth=sel["rows_with_executable_depth"],
               rows_missing_depth_by_reason=dict(sel["missing_depth_by_reason"].most_common()),
               rejected_before_scoring=sel["rejected_before_scoring"],
               rejected_before_scoring_by_reason=dict(sel["rejected_by_reason"].most_common()))
    if abort_reason:
        out["status"] = "ABORTED"
    return out


def _policy_input(row, *, series, mv, cv, bv) -> PolicyInput:
    prices = ExecutablePrices(
        yes_bid=row.get("yes_bid"), yes_ask=row.get("yes_ask"), no_bid=row.get("no_bid"),
        no_ask=row.get("no_ask"), yes_depth=row.get("yes_ask_size"), no_depth=row.get("no_ask_size"),
        yes_spread=row.get("yes_spread"), no_spread=row.get("no_spread"))
    fr = SourceFreshness(
        book_age_ms=row.get("book_age_ms"), underlying_age_ms=row.get("underlying_age_ms"),
        deribit_age_ms=row.get("deribit_age_ms"), coinbase_stale=bool(row.get("coinbase_stale")),
        binance_stale=bool(row.get("binance_stale")))
    return PolicyInput(
        series=series, ticker=row.get("ticker"), as_of_ts_ms=row.get("as_of_ts_ms"),
        market_open_ts_ms=row.get("market_open_ts_ms"), market_close_ts_ms=row.get("market_close_ts_ms"),
        seconds_to_close=row.get("seconds_to_close"),
        calibrated_probability_yes=row.get("calibrated_probability_yes"),
        model_probability_yes=row.get("model_probability_yes"),
        feature_schema_version=None,  # dataset feature_set_version != model_schema_version; checked at promotion
        book_ok=bool(row.get("book_ok")), has_underlying=bool(row.get("has_underlying")),
        reference_start_price=row.get("reference_start_price"), prices=prices, freshness=fr,
        model_validity=mv, calibration_validity=cv, backtest_validity=bv, feature_snapshot=row)


def _record(r, pdec, edge, manifest, rt, mode, state, reasons, fr_gate=None,
            feature_row_age_ms=None) -> dict:
    fr_gate = fr_gate or {}
    und = fr_gate.get("underlying") or {}
    return {
        "runtime_mode": mode,
        "promotion_manifest_path": rt["promo"].get("manifest_path"),
        "model_artifact_path": rt["model_path"],
        "calibrator_artifact_path": rt["calibrator_path"],
        "model_sha256": manifest.get("model_artifact_sha256"),
        "calibrator_sha256": manifest.get("calibrator_artifact_sha256"),
        "ticker": r.get("ticker"), "as_of_ts_ms": r.get("as_of_ts_ms"),
        "market_close_ts_ms": r.get("market_close_ts_ms"), "seconds_to_close": r.get("seconds_to_close"),
        "decision_state": state, "policy_decision_state": pdec.decision_state,
        "selected_side": pdec.selected_side,
        "model_probability_yes": pdec.model_probability_yes,
        "calibrated_probability_yes": pdec.calibrated_probability_yes,
        "probability_lower": edge.confidence_interval_low, "probability_upper": edge.confidence_interval_high,
        "executable_yes_price": pdec.executable_yes_price, "executable_no_price": pdec.executable_no_price,
        "selected_net_edge": pdec.selected_net_edge,
        "edge_policy_state": edge.state, "edge_policy_side": edge.side,
        "edge_final_cents": edge.final_policy_edge_cents, "edge_raw_cents": edge.raw_edge_cents,
        "edge_required_cents": edge.required_edge_cents, "edge_max_acceptable_price": edge.max_acceptable_price,
        "edge_reason_codes": edge.reason_codes, "reason_codes": reasons,
        # would this have been a PAPER_CANDIDATE absent shadow-suppression?
        "would_be_paper_candidate": ("SHADOW_WOULD_BE_PAPER_CANDIDATE" in reasons
                                     or state == PAPER_CANDIDATE),
        # OFFICIAL settlement label (post-close) — used ONLY to settle a PAPER fill in
        # replay (never an input to the decision). Mirrors backtest/paper-sim settlement.
        "label_yes_resolved": r.get("label_yes_resolved"),
        # ----- source freshness (decision-grade; within-row ages + fallback) -----
        "freshness_ok": fr_gate.get("ok"),
        "freshness_reasons": fr_gate.get("reasons", []),
        "quote_age_ms": r.get("quote_age_ms"),
        "book_age_ms": fr_gate.get("book_age_ms"),
        "book_age_basis": r.get("book_age_basis"),
        "book_age_method": r.get("book_age_method"),
        "book_age_source": r.get("book_age_source"),
        "book_age_confidence": r.get("book_age_confidence"),
        "book_recv_ms": r.get("book_recv_ms") or r.get("recv_ms"),
        "book_source_ts_ms": r.get("book_source_ts_ms") or r.get("source_ts_ms"),
        "book_timestamp_joined_from_normalized": bool(r.get("book_timestamp_joined_from_normalized")),
        "book_decision_stale": fr_gate.get("book_decision_stale"),
        "coinbase_feed_age_ms": und.get("coinbase_age_ms"),
        "binance_feed_age_ms": und.get("binance_age_ms"),
        "coinbase_decision_stale": und.get("coinbase_decision_stale"),
        "binance_decision_stale": und.get("binance_decision_stale"),
        "underlying_reference_source": und.get("reference_source"),
        "underlying_fallback_used": und.get("fallback_used"),
        "underlying_decision_stale": und.get("underlying_decision_stale"),
        "deribit_age_ms": r.get("deribit_age_ms"),
        "deribit_stale": r.get("deribit_stale"),
        # wall-clock age of the feature row evaluated (now - as_of) — exposes stale stored rows
        "feature_row_age_ms": feature_row_age_ms,
        "live_submission_allowed": False,
    }


# --------------------------------------------------------------------------- #
# Runners
# --------------------------------------------------------------------------- #
def runtime_status(config, *, series: str = "KXBTC15M") -> dict:
    """Read-only paper-runtime status: mode, manifest validity, can-emit summary."""
    mode = config.model_runtime_mode
    promo = load_active_promotion(config, series=series)
    pc = config.paper_policy
    can_emit = bool(mode == "paper" and promo.get("valid") and pc.enabled)
    out = {
        "series": series, "model_runtime_mode": mode,
        "modes": {"disabled": "no candidates", "shadow": "score+log only (no fills)",
                  "paper": "PAPER_CANDIDATE+fills if all gates pass", "live": "NOT SUPPORTED"},
        "paper_policy_enabled": pc.enabled,
        "promotion_manifest_exists": promo.get("exists", False),
        "promotion_manifest_valid": promo.get("valid", False),
        "promotion_blockers": promo.get("blockers", []),
        "manifest_path": promo.get("manifest_path"),
        "can_emit_paper_candidate": can_emit,
        "live_submission_allowed": False,
        "require_edge_policy": pc.require_edge_policy,
        "require_promoted_paper_model": pc.require_promoted_paper_model,
    }
    if promo.get("valid"):
        man = promo["manifest"]
        out["promoted"] = {
            "model_path": man.get("model_artifact_path"), "model_sha256": man.get("model_artifact_sha256"),
            "calibrator_path": man.get("calibrator_artifact_path"),
            "calibrator_sha256": man.get("calibrator_artifact_sha256"),
            "promoted_for": man.get("promoted_for"), "live_approved": man.get("live_approved"),
            "promoted_at": man.get("promoted_at"), "model_type": man.get("model_type"),
            "calibrator_type": man.get("calibrator_type")}
    blockers = list(promo.get("blockers", []))
    if mode == "disabled":
        blockers.append("RUNTIME_MODE_DISABLED")
    if not pc.enabled:
        blockers.append("PAPER_POLICY_DISABLED")
    out["why_cannot_emit"] = blockers
    return out


def run_shadow(config, *, series: str = "KXBTC15M", seconds: float = 60.0, limit: int = 25) -> dict:
    """Shadow run: score recent recorded snapshots with the promoted artifacts, run the
    policy + edge gates, write SHADOW_DECISION rows + a report. No orders, no fills, no live.

    ``seconds`` bounds an optional short freshness window; this build evaluates the most
    recent recorded dataset snapshots (offline-safe) rather than starting a long poll.
    """
    # Shadow always evaluates in shadow semantics regardless of configured mode, but it
    # still requires a valid promotion (else it reports blockers).
    ev = evaluate_paper_rows(config, series=series, mode="shadow", limit=limit)
    ev["seconds_window"] = seconds
    ledger_file = report_file = None
    if ev.get("decisions"):
        ledger_file = _write_shadow_ledger(config, ev["decisions"])
    report_file = _write_shadow_report(config, ev)
    ev["shadow_ledger_file"] = ledger_file
    ev["shadow_report_file"] = report_file
    return ev


def _write_shadow_ledger(config, rows: list[dict]) -> str:
    d = config.data_path() / "paper"
    d.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = d / f"kalshi_shadow_decisions-{day}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, default=str) + "\n")
    return str(path)


def _write_shadow_report(config, ev: dict) -> str:
    d = config.reports_path() / "models"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"kalshi_shadow_run_{_ts()}.md"
    lines = [
        f"# Kalshi SHADOW run — {ev['series']}", "",
        f"- runtime_mode: shadow (forced)  configured_mode: {config.model_runtime_mode}",
        f"- manifest_valid: {ev.get('manifest_valid')}  status: {ev.get('status')}",
        f"- manifest_path: {ev.get('manifest_path')}",
        f"- model: {ev.get('model_path')}",
        f"- calibrator: {ev.get('calibrator_path')}",
        f"- rows_evaluated: {ev.get('n_rows_evaluated')}  calibration_buckets: {ev.get('calibration_buckets')}",
        f"- decisions_by_state: {ev.get('decisions_by_state')}",
        f"- shadow_decisions: {ev.get('shadow_decisions')}  paper_candidates: {ev.get('paper_candidates')} "
        "(MUST be 0 in shadow)",
        f"- blockers: {ev.get('blockers')}",
        "", "## Safety",
        "- SHADOW ONLY: scores + logs; NEVER emits PAPER_CANDIDATE; NEVER paper-fills; NEVER live.",
        "- Artifacts loaded ONLY from the paper-promotion manifest (verified SHA + is_promoted +",
        "  non-diagnostic + calibrated); never newest-by-mtime; staged artifacts never used.",
        "- live_submission_allowed=false.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)
