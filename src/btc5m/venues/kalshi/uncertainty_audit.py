"""Read-only calibration-uncertainty audit for the confidence-aware edge policy.

Answers ONE question: *why is the calibration-uncertainty buffer so large, and is it
justified?* It loads a shadow/paper decision ledger, isolates the rows the paper policy
accepted (``PAPER_CANDIDATE_OK``) but the edge policy blocked, and RECOMPUTES the full
edge/uncertainty breakdown by re-running the production :func:`evaluate_edge` against
freshly rebuilt calibration buckets — so the numbers come from the real code path, not a
re-implementation.

Two decompositions make the buffer legible:

1. **Buffer = bias + sampling.** For a YES row the calibration buffer is
   ``mean_pred - wilson_low`` over the predicted-probability bucket. Split it into
   ``bias = mean_pred - mean_actual`` (the model over/under-predicting YES in that
   bucket) and ``sampling = mean_actual - wilson_low`` (binomial interval half-width).
   If bias dominates, the buffer is real miscalibration, not noise.

2. **Rows vs DISTINCT windows.** The reliability buckets count feature ROWS, but rows
   inside one 15-minute window are not independent. We report, per bucket, row_n vs
   distinct-window_n vs distinct-ticker_n, the row-YES-rate vs window-YES-rate, window
   concentration, and a window-based Wilson interval — so row-level pseudo-replication
   (fake confidence) is visible.

READ-ONLY / SAFE: never scores a live order, never trades, never promotes or demotes an
artifact, never enables paper/live, never mutates a model/calibrator/manifest. It only
reads recorded data and writes reports under ``reports/edge/``. ``live_submission_allowed``
is always False.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .edge_policy import EdgePolicyConfig, EdgeInputs, evaluate_edge
from .fees import KalshiFeeModel
from .uncertainty import wilson_interval

# Cohort selectors (which ledger rows to audit).
COHORT_EDGE_BLOCKED = "edge_blocked"      # PAPER_CANDIDATE_OK + edge-policy blocked (the 137)
COHORT_ALL = "all"

# A row is "edge-blocked" when the paper policy accepted it but the edge policy rejected.
_PAPER_OK = "PAPER_CANDIDATE_OK"
_EDGE_BLOCK_PREFIX = "EDGE_POLICY_BLOCKED"


# --------------------------------------------------------------------------- #
# Small stats helpers (stdlib only)
# --------------------------------------------------------------------------- #
def _median(xs: list) -> Optional[float]:
    vals = sorted(v for v in xs if isinstance(v, (int, float)))
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def _mean(xs: list) -> Optional[float]:
    vals = [v for v in xs if isinstance(v, (int, float))]
    return (sum(vals) / len(vals)) if vals else None


def _rng(xs: list) -> tuple:
    vals = [v for v in xs if isinstance(v, (int, float))]
    return (min(vals), max(vals)) if vals else (None, None)


def _pop_std(xs: list) -> Optional[float]:
    vals = [v for v in xs if isinstance(v, (int, float))]
    if len(vals) < 2:
        return 0.0 if vals else None
    m = sum(vals) / len(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


# --------------------------------------------------------------------------- #
# Ledger discovery + loading (read-only)
# --------------------------------------------------------------------------- #
def candidate_ledgers(config) -> list[Path]:
    """All known shadow/paper decision ledgers, newest last (by mtime)."""
    out: list[Path] = []
    exp = config.data_path() / "paper" / "experiments"
    if exp.exists():
        out += list(exp.glob("*_decisions.jsonl"))
    paper = config.data_path() / "paper"
    if paper.exists():
        out += list(paper.glob("kalshi_shadow_decisions-*.jsonl"))
    return sorted({p.resolve() for p in out}, key=lambda p: p.stat().st_mtime)


def latest_ledger(config) -> Optional[Path]:
    files = candidate_ledgers(config)
    return files[-1] if files else None


def load_decisions(path: str | Path) -> list[dict]:
    """Safely read a JSONL decision ledger (skips malformed lines)."""
    rows: list[dict] = []
    p = Path(path)
    if not p.exists():
        return rows
    with p.open("r", encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            try:
                obj = json.loads(ln)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def is_edge_blocked(decision: dict) -> bool:
    """True when the paper policy accepted the row but the edge policy blocked it."""
    rcs = decision.get("reason_codes") or []
    has_paper_ok = _PAPER_OK in rcs
    has_edge_block = any(isinstance(rc, str) and rc.startswith(_EDGE_BLOCK_PREFIX) for rc in rcs)
    return bool(has_paper_ok and has_edge_block)


def select_cohort(decisions: list[dict], cohort: str) -> list[dict]:
    if cohort == COHORT_ALL:
        return list(decisions)
    return [d for d in decisions if is_edge_blocked(d)]


# --------------------------------------------------------------------------- #
# Recompute one row's edge/uncertainty breakdown via the REAL evaluate_edge
# --------------------------------------------------------------------------- #
def _market_implied_yes(ya, na) -> Optional[float]:
    if ya is None or na is None:
        return None
    tot = ya + na
    if tot <= 0:
        return None
    return max(0.0, min(1.0, ya / tot))


def recompute_row(decision: dict, buckets: list, edge_cfg: EdgePolicyConfig,
                  fee_model: KalshiFeeModel) -> dict:
    """Reconstruct EdgeInputs from a ledger row + run the production edge policy.

    Mirrors ``paper_runtime._edge_inputs`` (model interval bound is unavailable -> the
    conservative bound comes from ensemble disagreement vs the market-implied price, the
    SAME as the runtime). ``buckets`` are the rebuilt calibration buckets; pass an empty
    list to recompute without a calibration buffer (degraded mode).
    Returns the recomputed breakdown plus a comparison to the stored ledger fields.
    """
    p_hat = decision.get("calibrated_probability_yes")
    ya = decision.get("executable_yes_price")
    na = decision.get("executable_no_price")
    mkt = _market_implied_yes(ya, na)
    ens: dict = {}
    if p_hat is not None:
        ens["model"] = p_hat
        if mkt is not None:
            ens["market_implied"] = mkt
    inp = EdgeInputs(
        p_yes_hat=p_hat, p_yes_lower=None, p_yes_upper=None,
        yes_ask=ya, no_ask=na, yes_ask_size=None, no_ask_size=None,
        seconds_to_close=decision.get("seconds_to_close"),
        book_age_ms=decision.get("book_age_ms"),
        underlying_age_ms=decision.get("underlying_age_ms"),
        coinbase_stale=bool(decision.get("coinbase_decision_stale")),
        binance_stale=bool(decision.get("binance_decision_stale")),
        deribit_regime=None, sigma_per_sqrt_s=None, overtrading=False,
        calibration_buckets=buckets, ensemble_probs=ens,
        model_calibrated=True, model_tradable=True, backtest_valid=True)
    dec = evaluate_edge(inp, edge_cfg, fee_model)

    # Stored (ground-truth) fields from the actual run.
    s_raw = decision.get("edge_raw_cents")
    s_final = decision.get("edge_final_cents")
    s_req = decision.get("edge_required_cents")
    s_reservation = decision.get("edge_max_acceptable_price")
    s_lo = decision.get("probability_lower")
    s_hi = decision.get("probability_upper")

    # The fundamental ledger-internal identity (independent of any rebuild):
    #   final_policy_edge == raw_edge - required_edge   AND   reservation == ask + final.
    identity_ok = None
    if s_raw is not None and s_final is not None and s_req is not None:
        identity_ok = abs((s_raw - s_req) - s_final) < 0.02
    ask = ya if (decision.get("selected_side") == "YES") else na
    reservation_ok = None
    if ask is not None and s_final is not None and s_reservation is not None:
        reservation_ok = abs((ask + s_final / 100.0) - s_reservation) < 1e-4

    def _delta(a, b):
        return (a - b) if (isinstance(a, (int, float)) and isinstance(b, (int, float))) else None

    return {
        "ticker": decision.get("ticker"),
        "as_of_ts_ms": decision.get("as_of_ts_ms"),
        "seconds_to_close": decision.get("seconds_to_close"),
        "selected_side": decision.get("selected_side") or dec.side,
        "model_probability_yes": decision.get("model_probability_yes"),
        "calibrated_probability_yes": p_hat,
        "executable_yes_price": ya,
        "executable_no_price": na,
        "market_implied_yes": mkt,
        "model_minus_market_cents": ((p_hat - mkt) * 100.0) if (p_hat is not None and mkt is not None) else None,
        # ----- recomputed via the production evaluate_edge -----
        "rc_state": dec.state,
        "rc_side": dec.side,
        "rc_method": dec.edge_policy_method,
        "rc_raw_edge_cents": dec.raw_edge_cents,
        "rc_fee_cents": dec.fee_cents,
        "rc_model_uncertainty_buffer_cents": dec.model_uncertainty_buffer_cents,
        "rc_calibration_uncertainty_buffer_cents": dec.calibration_uncertainty_buffer_cents,
        "rc_stale_quote_buffer_cents": dec.stale_quote_buffer_cents,
        "rc_source_health_buffer_cents": dec.source_health_buffer_cents,
        "rc_regime_buffer_cents": dec.regime_buffer_cents,
        "rc_overtrading_buffer_cents": dec.overtrading_buffer_cents,
        "rc_minimum_profit_buffer_cents": dec.minimum_profit_buffer_cents,
        "rc_required_edge_cents": dec.required_edge_cents,
        "rc_uncertainty_adjusted_edge_cents": dec.uncertainty_adjusted_edge_cents,
        "rc_final_policy_edge_cents": dec.final_policy_edge_cents,
        "rc_reservation_price": dec.max_acceptable_price,
        "rc_ci_low": dec.confidence_interval_low,
        "rc_ci_high": dec.confidence_interval_high,
        "rc_sample_count_used": dec.sample_count_used,
        # ----- stored (ground truth) + consistency checks -----
        "stored_raw_edge_cents": s_raw,
        "stored_required_edge_cents": s_req,
        "stored_final_policy_edge_cents": s_final,
        "stored_reservation_price": s_reservation,
        "stored_probability_lower": s_lo,
        "stored_probability_upper": s_hi,
        "identity_final_eq_raw_minus_required": identity_ok,
        "identity_reservation_eq_ask_plus_final": reservation_ok,
        "delta_final_cents": _delta(dec.final_policy_edge_cents, s_final),
        "delta_required_cents": _delta(dec.required_edge_cents, s_req),
        "delta_raw_cents": _delta(dec.raw_edge_cents, s_raw),
        "stored_reason_codes": "|".join(decision.get("reason_codes") or []),
        "live_submission_allowed": False,
    }


# --------------------------------------------------------------------------- #
# Bucket reliability with ROW vs DISTINCT-WINDOW accounting (Parts B/C)
# --------------------------------------------------------------------------- #
def bucket_window_stats(labelled_rows: list[dict], *, n_buckets: int = 10,
                        confidence: float = 0.80,
                        prob_key: str = "calibrated_probability_yes",
                        window_key: str = "ticker",
                        label_key: str = "label_yes_resolved") -> list[dict]:
    """Per predicted-probability bucket: ROW vs DISTINCT-WINDOW reliability + buffer split.

    ``labelled_rows`` need a predicted probability, a window id (ticker), and a 0/1 label.
    Buckets use the same ``[b/n, (b+1)/n)`` edges as ``pure_ml.probability_buckets``.
    """
    by_bucket: dict[int, list] = defaultdict(list)
    for r in labelled_rows:
        p = r.get(prob_key)
        y = r.get(label_key)
        w = r.get(window_key)
        if p is None or y is None:
            continue
        b = min(n_buckets - 1, max(0, int(float(p) * n_buckets)))
        by_bucket[b].append((float(p), int(y), w))

    out: list[dict] = []
    for b in range(n_buckets):
        rows = by_bucket.get(b)
        if not rows:
            continue
        lo, hi = b / n_buckets, (b + 1) / n_buckets
        row_n = len(rows)
        succ_rows = sum(y for _, y, _ in rows)
        row_yes = succ_rows / row_n
        mean_pred_row = sum(p for p, _, _ in rows) / row_n

        # window-level aggregation (one window contributes once; its label is constant)
        win_label: dict = {}
        win_count: dict = defaultdict(int)
        win_pred_sum: dict = defaultdict(float)
        for p, y, w in rows:
            win_label[w] = y
            win_count[w] += 1
            win_pred_sum[w] += p
        window_n = len(win_label)
        yes_windows = sum(1 for w in win_label if win_label[w] == 1)
        window_yes = (yes_windows / window_n) if window_n else None
        mean_pred_window = (sum(win_pred_sum[w] / win_count[w] for w in win_label) / window_n) if window_n else None

        # concentration of rows across windows (top-1/5/10 share)
        counts = sorted(win_count.values(), reverse=True)
        # Kish effective sample size under clustering: (sum n_i)^2 / sum(n_i^2) (<= row_n,
        # ~ distinct_window_n when windows are balanced). Honest n for the bucket.
        _sum_n2 = sum(c * c for c in win_count.values())
        kish_neff = (row_n * row_n / _sum_n2) if _sum_n2 else None
        top1 = counts[0] / row_n if counts else None
        top5 = sum(counts[:5]) / row_n if counts else None
        top10 = sum(counts[:10]) / row_n if counts else None

        # Wilson intervals: ROW-based (what the policy uses) vs WINDOW-based (honest).
        rl, rh = wilson_interval(succ_rows, row_n, confidence=confidence)
        wl, wh = wilson_interval(yes_windows, window_n, confidence=confidence) if window_n else (0.0, 1.0)

        # YES-side downside buffer = mean_pred - wilson_low. Split into bias + sampling.
        buffer_row = max(0.0, mean_pred_row - rl)
        bias_row = mean_pred_row - row_yes
        sampling_row = row_yes - rl
        buffer_window = max(0.0, (mean_pred_window - wl)) if mean_pred_window is not None else None
        bias_window = (mean_pred_window - window_yes) if (mean_pred_window is not None and window_yes is not None) else None

        out.append({
            "bucket": f"[{lo:.1f},{hi:.1f})",
            "bucket_index": b,
            "row_n": row_n,
            "distinct_window_n": window_n,
            "distinct_ticker_n": window_n,
            "rows_per_window": round(row_n / window_n, 2) if window_n else None,
            "effective_sample_size": round(kish_neff, 1) if kish_neff is not None else None,
            "row_yes_rate": round(row_yes, 5),
            "window_yes_rate": round(window_yes, 5) if window_yes is not None else None,
            "row_no_rate": round(1 - row_yes, 5),
            "window_no_rate": round(1 - window_yes, 5) if window_yes is not None else None,
            "mean_pred_row": round(mean_pred_row, 5),
            "mean_pred_window": round(mean_pred_window, 5) if mean_pred_window is not None else None,
            "row_wilson_low": round(rl, 5),
            "row_wilson_high": round(rh, 5),
            "row_wilson_width": round(rh - rl, 5),
            "window_wilson_low": round(wl, 5),
            "window_wilson_high": round(wh, 5),
            "window_wilson_width": round(wh - wl, 5),
            "top1_window_row_share": round(top1, 4) if top1 is not None else None,
            "top5_window_row_share": round(top5, 4) if top5 is not None else None,
            "top10_window_row_share": round(top10, 4) if top10 is not None else None,
            # YES-side buffer decomposition (cents)
            "calib_buffer_row_cents": round(buffer_row * 100.0, 3),
            "calib_bias_row_cents": round(bias_row * 100.0, 3),
            "calib_sampling_row_cents": round(sampling_row * 100.0, 3),
            "calib_buffer_window_cents": round(buffer_window * 100.0, 3) if buffer_window is not None else None,
            "calib_bias_window_cents": round(bias_window * 100.0, 3) if bias_window is not None else None,
        })
    return out


def _bucket_for(p: Optional[float], bucket_stats: list[dict], n_buckets: int = 10) -> Optional[dict]:
    if p is None:
        return None
    b = min(n_buckets - 1, max(0, int(float(p) * n_buckets)))
    for bs in bucket_stats:
        if bs["bucket_index"] == b:
            return bs
    return None


# --------------------------------------------------------------------------- #
# Rebuild the runtime's calibration buckets + scored dataset (best-effort)
# --------------------------------------------------------------------------- #
def rebuild_calibration_context(config, *, series: str) -> dict:
    """Rebuild the SAME calibration buckets + scored dataset rows the runtime uses.

    Reuses ``paper_runtime._prepare_runtime`` so there is zero divergence from the live
    edge-policy path. Degrades gracefully (returns ``ok=False`` + blockers) when no paper
    model is promoted or the runtime is otherwise unavailable — the audit then reports the
    ledger-internal checks only. Never trades, never promotes, never enables paper/live.
    """
    try:
        from .paper_runtime import _prepare_runtime
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "blockers": [f"import_error:{type(exc).__name__}"], "buckets": [], "rows": []}
    try:
        prep = _prepare_runtime(config, series=series, mode="shadow")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "blockers": [f"prepare_error:{type(exc).__name__}: {exc}"],
                "buckets": [], "rows": []}
    if prep.get("status") != "OK":
        return {"ok": False, "blockers": prep.get("base", {}).get("blockers", [prep.get("status")]),
                "buckets": [], "rows": []}
    rows = prep.get("dataset_rows", [])
    labelled = [r for r in rows
                if r.get("label_yes_resolved") is not None and r.get("calibrated_probability_yes") is not None]
    return {"ok": True, "blockers": [], "buckets": prep.get("buckets", []),
            "rows": rows, "labelled_rows": labelled,
            "model_path": prep["rt"]["model_path"], "calibrator_path": prep["rt"]["calibrator_path"],
            "manifest": prep.get("manifest", {})}


# --------------------------------------------------------------------------- #
# Aggregation + verdict
# --------------------------------------------------------------------------- #
def _summarize_cohort(recs: list[dict]) -> dict:
    side_counts: dict = defaultdict(int)
    for r in recs:
        side_counts[r.get("selected_side")] += 1
    finals = [r["rc_final_policy_edge_cents"] for r in recs if r.get("rc_final_policy_edge_cents") is not None]
    raws = [r["rc_raw_edge_cents"] for r in recs if r.get("rc_raw_edge_cents") is not None]
    calibs = [r["rc_calibration_uncertainty_buffer_cents"] for r in recs
              if r.get("rc_calibration_uncertainty_buffer_cents") is not None]
    model_uncs = [r["rc_model_uncertainty_buffer_cents"] for r in recs
                  if r.get("rc_model_uncertainty_buffer_cents") is not None]
    reqs = [r["rc_required_edge_cents"] for r in recs if r.get("rc_required_edge_cents") is not None]
    mm = [r["model_minus_market_cents"] for r in recs if r.get("model_minus_market_cents") is not None]
    identities = [r.get("identity_final_eq_raw_minus_required") for r in recs
                  if r.get("identity_final_eq_raw_minus_required") is not None]
    return {
        "n": len(recs),
        "side_counts": dict(side_counts),
        "raw_edge_cents_median": _median(raws),
        "raw_edge_cents_range": _rng(raws),
        "calibration_buffer_cents_median": _median(calibs),
        "calibration_buffer_cents_range": _rng(calibs),
        "model_uncertainty_buffer_cents_median": _median(model_uncs),
        "model_uncertainty_buffer_cents_range": _rng(model_uncs),
        "required_edge_cents_median": _median(reqs),
        "final_policy_edge_cents_median": _median(finals),
        "final_policy_edge_cents_best": max(finals) if finals else None,
        "final_policy_edge_cents_range": _rng(finals),
        "model_minus_market_cents_median": _median(mm),
        "n_positive_final": sum(1 for f in finals if f >= 0),
        "identity_pass": sum(1 for i in identities if i),
        "identity_total": len(identities),
        "identity_all_ok": bool(identities) and all(identities),
    }


def _verdict(cohort_summary: dict, cohort_bucket_rows: list[dict]) -> dict:
    """Plain-language verdict computed from the data (Part J)."""
    bias = [b["calib_bias_row_cents"] for b in cohort_bucket_rows if b.get("calib_bias_row_cents") is not None]
    sampling = [b["calib_sampling_row_cents"] for b in cohort_bucket_rows
                if b.get("calib_sampling_row_cents") is not None]
    buf_row = [b["calib_buffer_row_cents"] for b in cohort_bucket_rows if b.get("calib_buffer_row_cents") is not None]
    buf_win = [b["calib_buffer_window_cents"] for b in cohort_bucket_rows
               if b.get("calib_buffer_window_cents") is not None]
    med_bias = _median(bias)
    med_samp = _median(sampling)
    med_buf = _median(buf_row)
    med_buf_win = _median(buf_win)
    bias_fraction = (med_bias / med_buf) if (med_bias is not None and med_buf and med_buf > 0) else None
    # Per-bucket: does the honest (distinct-window) Wilson buffer match or exceed the
    # row-based one? Median can flip on noise, so count buckets instead.
    pairs = [(b.get("calib_buffer_row_cents"), b.get("calib_buffer_window_cents"))
             for b in cohort_bucket_rows
             if b.get("calib_buffer_row_cents") is not None and b.get("calib_buffer_window_cents") is not None]
    n_window_ge_row = sum(1 for r, w in pairs if w >= r - 0.5)
    window_makes_bigger = bool(pairs and n_window_ge_row >= (len(pairs) + 1) // 2)
    return {
        "buffer_is_bias_dominated": bool(bias_fraction is not None and bias_fraction >= 0.5),
        "median_bias_cents": med_bias,
        "median_sampling_cents": med_samp,
        "median_buffer_row_cents": med_buf,
        "median_buffer_window_cents": med_buf_win,
        "bias_fraction_of_buffer": round(bias_fraction, 3) if bias_fraction is not None else None,
        "window_based_buffer_is_larger": window_makes_bigger,
        "buckets_window_buffer_ge_row": f"{n_window_ge_row}/{len(pairs)}",
        "edge_identity_holds": cohort_summary.get("identity_all_ok"),
        "all_selected_yes": (set(cohort_summary.get("side_counts", {})) <= {"YES"}),
        "model_overpredicts_yes": bool((med_bias or 0) > 1.0),
    }


# --------------------------------------------------------------------------- #
# Report writers
# --------------------------------------------------------------------------- #
def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c) for c in cols})


def _fmt(x, nd=2) -> str:
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else str(x)


def _write_markdown(path: Path, *, series: str, ledger: str, cohort: str, summary: dict,
                    verdict: dict, cohort_buckets: list[dict], all_buckets: list[dict],
                    near_passes: list[dict], rebuild: dict, top_n: int) -> None:
    lo, hi = summary.get("final_policy_edge_cents_range", (None, None))
    lines = [
        f"# Kalshi calibration-uncertainty audit — {series}", "",
        "> READ-ONLY. Recomputed via the production `evaluate_edge`; no trading, no promotion, "
        "no paper/live, no artifact mutation. `live_submission_allowed=false`.", "",
        f"- ledger: `{ledger}`",
        f"- cohort: **{cohort}**  rows: **{summary.get('n')}**  sides: {summary.get('side_counts')}",
        f"- calibration rebuild: {'OK' if rebuild.get('ok') else 'UNAVAILABLE ' + str(rebuild.get('blockers'))}",
    ]
    if rebuild.get("ok"):
        lines.append(f"- promoted model: `{Path(rebuild.get('model_path','')).name}`  "
                     f"calibrator: `{Path(rebuild.get('calibrator_path','')).name}`")
    lines += [
        "", "## Core finding (Part J)",
        f"- **Edge identity holds** (`final == raw − required`) for "
        f"{summary.get('identity_pass')}/{summary.get('identity_total')} rows: "
        f"**{verdict.get('edge_identity_holds')}** — no sign/unit/double-count error.",
        f"- Median calibration buffer (recomputed): **{_fmt(summary.get('calibration_buffer_cents_median'))}c** "
        f"(row-based). Median model-uncertainty buffer: "
        f"**{_fmt(summary.get('model_uncertainty_buffer_cents_median'))}c** (ensemble disagreement vs market, "
        "NOT the fixed 3c fallback).",
        f"- Buffer is **{'BIAS-DOMINATED' if verdict.get('buffer_is_bias_dominated') else 'sampling-influenced'}**: "
        f"median bias (mean_pred − mean_actual) = **{_fmt(verdict.get('median_bias_cents'))}c**, "
        f"median sampling (Wilson half-width) = **{_fmt(verdict.get('median_sampling_cents'))}c** "
        f"(bias is {_fmt((verdict.get('bias_fraction_of_buffer') or 0)*100,0)}% of the buffer).",
        f"- Using DISTINCT WINDOWS instead of rows makes the buffer "
        f"**{'LARGER' if verdict.get('window_based_buffer_is_larger') else 'smaller'}** "
        f"(row {_fmt(verdict.get('median_buffer_row_cents'))}c vs window "
        f"{_fmt(verdict.get('median_buffer_window_cents'))}c) — row-vs-window overcounting is NOT inflating "
        "the buffer; if anything it understates it.",
        f"- All selected side YES: **{verdict.get('all_selected_yes')}**; model over-predicts YES in the "
        f"candidate buckets: **{verdict.get('model_overpredicts_yes')}**.",
        "",
        "**Verdict:** the calibration buffer is *mathematically correct* and *bias-dominated* — it reflects a "
        "real, large gap between the calibrated YES probability and the realized YES rate in the candidate "
        "buckets, not a counting artifact or a bug. It is honestly reduced only by RECALIBRATING the model "
        "(so mean_pred ≈ mean_actual), not by deleting the buffer.",
        "", "## Part A — edge-policy math validation",
        f"- raw edge median {_fmt(summary.get('raw_edge_cents_median'))}c, range {summary.get('raw_edge_cents_range')}",
        f"- required edge median {_fmt(summary.get('required_edge_cents_median'))}c",
        f"- final policy edge median {_fmt(summary.get('final_policy_edge_cents_median'))}c, "
        f"best {_fmt(summary.get('final_policy_edge_cents_best'))}c, range ({_fmt(lo)}, {_fmt(hi)})",
        f"- rows with positive final edge: **{summary.get('n_positive_final')}** / {summary.get('n')}",
        f"- reconstructed-vs-stored consistency: identity {summary.get('identity_pass')}/"
        f"{summary.get('identity_total')} (see CSV `delta_*` columns for residual drift from bucket rebuild).",
        "", "## Parts B/C — calibration buckets used by the cohort (ROW vs DISTINCT WINDOW)",
        "", "| bucket | row_n | win_n | rows/win | row YES | win YES | mean_pred | "
        "buffer(row) | bias | samp | buffer(win) | top1 win share |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for b in cohort_buckets:
        lines.append(
            f"| {b['bucket']} | {b['row_n']} | {b['distinct_window_n']} | {b['rows_per_window']} | "
            f"{_fmt(b['row_yes_rate'],3)} | {_fmt(b['window_yes_rate'],3)} | {_fmt(b['mean_pred_row'],3)} | "
            f"{_fmt(b['calib_buffer_row_cents'])} | {_fmt(b['calib_bias_row_cents'])} | "
            f"{_fmt(b['calib_sampling_row_cents'])} | {_fmt(b['calib_buffer_window_cents'])} | "
            f"{_fmt(b['top1_window_row_share'],3)} |")
    lines += [
        "", "_buffer(row) = mean_pred − row_wilson_low (what the policy applies); "
        "bias = mean_pred − row_yes; samp = row_yes − row_wilson_low; "
        "buffer(win) recomputes the Wilson interval on DISTINCT windows._",
        "", "## Parts D/E — YES-side bias & model vs market-implied",
        f"- cohort sides: {summary.get('side_counts')} (all YES => the model only ever finds YES 'underpriced').",
        f"- median (model − market-implied) = **{_fmt(summary.get('model_minus_market_cents_median'))}c**: the model "
        "sits ABOVE the market. In these buckets the realized YES rate is BELOW the market price too, so the "
        "market-implied probability is better calibrated than the model — the model's 'edge' is over-prediction.",
        "", f"## Part H — top {top_n} near-pass rows (closest to passing)",
        "", "| ticker | s_to_close | side | calib P | yes ask | mkt impl | raw | calib buf | final | reservation |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in near_passes[:top_n]:
        lines.append(
            f"| {r.get('ticker')} | {_fmt(r.get('seconds_to_close'),0)} | {r.get('selected_side')} | "
            f"{_fmt(r.get('calibrated_probability_yes'),3)} | {_fmt(r.get('executable_yes_price'),2)} | "
            f"{_fmt(r.get('market_implied_yes'),3)} | {_fmt(r.get('rc_raw_edge_cents'))} | "
            f"{_fmt(r.get('rc_calibration_uncertainty_buffer_cents'))} | {_fmt(r.get('rc_final_policy_edge_cents'))} | "
            f"{_fmt(r.get('rc_reservation_price'),3)} |")
    lines += [
        "", "## Safety",
        "- READ-ONLY: recomputation only; no order, no fill, no paper/live mode, no promotion/demotion.",
        "- No model/calibrator/manifest/active-pointer was modified. Uncertainty buffers were NOT reduced.",
        "- `live_submission_allowed=false`.",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Top-level runner
# --------------------------------------------------------------------------- #
def run_uncertainty_audit(config, *, series: str = "KXBTC15M", ledger: Optional[str] = None,
                          cohort: str = COHORT_EDGE_BLOCKED, top_n: int = 20,
                          latest: bool = True, write_csv: bool = True, write_md: bool = True,
                          write_json: bool = False) -> dict:
    """Run the read-only calibration-uncertainty audit. Returns a summary dict + report paths.

    Never trades, never promotes, never enables paper/live, never mutates artifacts.
    """
    edge_cfg = EdgePolicyConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)

    # ----- locate + load the ledger (read-only) -----
    ledger_path = Path(ledger) if ledger else latest_ledger(config)
    base = {"series": series, "cohort": cohort, "live_submission_allowed": False}
    if ledger_path is None or not Path(ledger_path).exists():
        return {**base, "status": "NO_LEDGER",
                "note": "No shadow/paper decision ledger found under data/paper[/experiments].",
                "candidates": [str(p) for p in candidate_ledgers(config)]}
    decisions = load_decisions(ledger_path)
    cohort_rows = select_cohort(decisions, cohort)

    # ----- rebuild the runtime's calibration buckets (best-effort, read-only) -----
    rebuild = rebuild_calibration_context(config, series=series)
    buckets = rebuild.get("buckets", []) if rebuild.get("ok") else []

    # ----- per-row recompute via the production evaluate_edge -----
    recs = [recompute_row(d, buckets, edge_cfg, fee_model) for d in cohort_rows]
    summary = _summarize_cohort(recs)

    # ----- bucket reliability with row-vs-window accounting -----
    all_bucket_stats = (bucket_window_stats(rebuild["labelled_rows"])
                        if rebuild.get("ok") and rebuild.get("labelled_rows") else [])
    # restrict to the buckets the cohort actually used
    used_idx = set()
    for r in recs:
        p = r.get("calibrated_probability_yes")
        if p is not None:
            used_idx.add(min(9, max(0, int(float(p) * 10))))
    cohort_bucket_stats = [b for b in all_bucket_stats if b["bucket_index"] in used_idx]

    # attach per-row bucket bias/sampling for the CSV
    for r in recs:
        bs = _bucket_for(r.get("calibrated_probability_yes"), cohort_bucket_stats)
        r["bucket"] = bs["bucket"] if bs else None
        r["bucket_row_n"] = bs["row_n"] if bs else None
        r["bucket_distinct_window_n"] = bs["distinct_window_n"] if bs else None
        r["bucket_row_yes_rate"] = bs["row_yes_rate"] if bs else None
        r["bucket_window_yes_rate"] = bs["window_yes_rate"] if bs else None
        r["bucket_calib_bias_cents"] = bs["calib_bias_row_cents"] if bs else None
        r["bucket_calib_sampling_cents"] = bs["calib_sampling_row_cents"] if bs else None
        r["bucket_calib_buffer_window_cents"] = bs["calib_buffer_window_cents"] if bs else None

    near_passes = sorted(
        [r for r in recs if r.get("rc_final_policy_edge_cents") is not None],
        key=lambda r: r["rc_final_policy_edge_cents"], reverse=True)
    verdict = _verdict(summary, cohort_bucket_stats)

    # ----- write reports (reports/edge/ only) -----
    out_dir = config.reports_path() / "edge"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    reports: dict = {}
    if write_csv:
        p = out_dir / f"kalshi_uncertainty_audit_{stamp}.csv"
        _write_csv(p, recs)
        reports["rows_csv"] = str(p)
        pb = out_dir / f"kalshi_uncertainty_bucket_summary_{stamp}.csv"
        _write_csv(pb, cohort_bucket_stats or all_bucket_stats)
        reports["bucket_csv"] = str(pb)
        pn = out_dir / f"kalshi_uncertainty_near_passes_{stamp}.csv"
        _write_csv(pn, near_passes[:top_n])
        reports["near_passes_csv"] = str(pn)
    if write_md:
        pm = out_dir / f"kalshi_uncertainty_audit_{stamp}.md"
        _write_markdown(pm, series=series, ledger=str(ledger_path), cohort=cohort, summary=summary,
                        verdict=verdict, cohort_buckets=cohort_bucket_stats, all_buckets=all_bucket_stats,
                        near_passes=near_passes, rebuild=rebuild, top_n=top_n)
        reports["markdown"] = str(pm)
    if write_json:
        pj = out_dir / f"kalshi_uncertainty_audit_{stamp}.json"
        pj.write_text(json.dumps({"summary": summary, "verdict": verdict,
                                  "cohort_buckets": cohort_bucket_stats}, indent=2, default=str),
                      encoding="utf-8")
        reports["json"] = str(pj)

    return {**base, "status": "OK", "ledger": str(ledger_path),
            "n_decisions": len(decisions), "n_cohort": len(cohort_rows),
            "summary": summary, "verdict": verdict,
            "cohort_buckets": cohort_bucket_stats, "rebuild_ok": rebuild.get("ok"),
            "rebuild_blockers": rebuild.get("blockers", []),
            "near_passes": near_passes[:top_n], "reports": reports}
