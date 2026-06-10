"""Per-source health for the Kalshi pipeline.

Reports, for every data source the Kalshi feature builder can use, whether it is
enabled, implemented vs stubbed, how fresh its recorded data is, and whether it
is required or optional. Pure read of recorded files + config — places no orders,
prints no secrets, makes no network calls.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from ...timeutils import now_ms
from .freshness import resolve_underlying, source_freshness

# Default LIVENESS threshold ("is the collector alive?") — intentionally LOOSER than
# the per-DECISION freshness threshold ("fresh enough to score / emit a candidate?").
# Both are overridden per-source from config.freshness; these are only fallbacks.
_STALE_MS = 60_000
# Default per-DECISION freshness (a tick older than this is too stale to trade on).
FEATURE_FRESHNESS_MS = 5_000


def _last_line(path: Path) -> Optional[dict]:
    """Return the last valid JSON object in a jsonl file (small tail read)."""
    try:
        last = None
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        last = json.loads(line)
                    except json.JSONDecodeError:
                        continue
        return last
    except OSError:
        return None


def _count_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())
    except OSError:
        return 0


def _today_file(d: Path, prefix: str) -> Optional[Path]:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    p = d / f"{prefix}-{day}.jsonl"
    return p if p.exists() else None


def _latest_file(d: Path, prefix: str) -> Optional[Path]:
    """Most recent ``{prefix}-*.jsonl`` (today's if present, else the newest)."""
    if not d.exists():
        return None
    files = sorted(d.glob(f"{prefix}-*.jsonl"))
    return files[-1] if files else None


def _latest_ts(row: Optional[dict], *keys: str) -> Optional[int]:
    if not isinstance(row, dict):
        return None
    ev = row.get("event") if isinstance(row.get("event"), dict) else row
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else ev
    for k in keys:
        for src in (ev, payload):
            v = src.get(k) if isinstance(src, dict) else None
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    continue
    return None


def _source_entry(
    *, name: str, enabled: bool, implemented: bool, required: bool,
    used_in_features: bool, raw_dir: Path, norm_dir: Path,
    raw_prefix: str, norm_prefix: str, price_keys: tuple[str, ...] = (),
    ts_keys: tuple[str, ...] = ("recv_ms", "exchange_ts_ms"),
    required_for_feature_generation: bool = False,
    feature_role: str = "",
    can_serve_as_spot_fallback: bool = False,
    liveness_ms: int = _STALE_MS,
    decision_ms: int = FEATURE_FRESHNESS_MS,
    extra_value_keys: tuple[str, ...] = (),
    note: str = "",
) -> dict:
    now = now_ms()
    raw_today = _today_file(raw_dir, raw_prefix)
    norm_today = _today_file(norm_dir, norm_prefix)
    # Freshness/price come from the newest available file (handles day rollover).
    raw_latest = _latest_file(raw_dir, raw_prefix)
    norm_latest = _latest_file(norm_dir, norm_prefix)
    last_raw = _last_line(raw_latest) if raw_latest else None
    last_norm = _last_line(norm_latest) if norm_latest else None
    latest_raw_ms = _latest_ts(last_raw, *ts_keys)
    latest_norm_ms = _latest_ts(last_norm, *ts_keys)
    newest = max([t for t in (latest_raw_ms, latest_norm_ms) if t is not None], default=None)
    age_ms = (now - newest) if newest is not None else None
    # ONE measured age, TWO thresholds: liveness (alive?) vs decision (trade-fresh?).
    fr = source_freshness(name, age_ms, liveness_ms=liveness_ms, decision_ms=decision_ms)
    stale = fr["liveness_stale"] if age_ms is not None else True  # back-compat: "stale" == liveness-stale
    if age_ms is None:
        stale_reason = "no recorded rows"
    elif stale:
        stale_reason = f"latest row age {age_ms}ms > liveness_threshold {liveness_ms}ms"
    else:
        stale_reason = None
    decision_reason = None
    if fr["decision_stale"] and age_ms is not None:
        decision_reason = f"latest row age {age_ms}ms > decision_threshold {decision_ms}ms (too stale to trade)"
    ev_norm = None
    if isinstance(last_norm, dict):
        ev_norm = last_norm.get("event") if isinstance(last_norm.get("event"), dict) else last_norm
    latest_price = None
    if price_keys and isinstance(ev_norm, dict):
        for k in price_keys:
            if ev_norm.get(k) is not None:
                latest_price = ev_norm.get(k)
                break
    latest_values: dict = {}
    if extra_value_keys and isinstance(ev_norm, dict):
        for k in extra_value_keys:
            if ev_norm.get(k) is not None:
                latest_values[k] = ev_norm.get(k)
    entry = {
        "source": name,
        "enabled": enabled,
        "implemented": implemented,
        "status": ("implemented" if implemented else "stubbed"),
        "required": required,
        "required_for_feature_generation": required_for_feature_generation,
        "feature_role": feature_role,
        "can_serve_as_spot_fallback": can_serve_as_spot_fallback,
        "used_in_kalshi_feature_builder": used_in_features,
        "rows_today_raw": _count_lines(raw_today) if raw_today else 0,
        "rows_today_normalized": _count_lines(norm_today) if norm_today else 0,
        "latest_raw_ts_ms": latest_raw_ms,
        "latest_normalized_ts_ms": latest_norm_ms,
        "data_age_ms": age_ms,
        # ----- LIVENESS (collector alive?) -----
        "liveness_age_ms": age_ms,
        "liveness_threshold_ms": liveness_ms,
        "liveness_stale": fr["liveness_stale"],
        # ----- DECISION freshness (fresh enough to trade?) -----
        "decision_age_ms": age_ms,
        "decision_threshold_ms": decision_ms,
        "decision_stale": fr["decision_stale"],
        "fresh_for_collection": fr["fresh_for_collection"],
        "fresh_for_decision": fr["fresh_for_decision"],
        "fresh_for_training": fr["fresh_for_training"],
        "fresh_for_paper_candidate": fr["fresh_for_paper_candidate"],
        # back-compat aliases ("stale" == liveness-stale; threshold is the liveness one)
        "stale_threshold_ms": liveness_ms,
        "feature_freshness_threshold_ms": (decision_ms if used_in_features else None),
        "stale": stale,
        "stale_reason": stale_reason,
        "decision_stale_reason": decision_reason,
        "latest_price": latest_price,
        "latest_values": latest_values,
        "last_error": None,
        "missing_reason": (None if (raw_latest or norm_latest) else "no recorded rows"),
        "note": note,
    }
    return entry


def assess_source_health(config) -> dict:
    """Return source-health for kalshi, coinbase, binance, deribit + notifier."""
    data = config.data_path()
    raw = data / "raw"
    norm = data / "normalized"
    deribit_cfg = getattr(config, "deribit", None)
    deribit_enabled = bool(getattr(deribit_cfg, "enabled", False))
    deribit_stale_ms = int(getattr(deribit_cfg, "stale_threshold_seconds", 180) or 180) * 1000
    fcfg = config.freshness

    sources = [
        _source_entry(
            name="kalshi", enabled=True, implemented=True, required=True, used_in_features=True,
            raw_dir=raw, norm_dir=norm, raw_prefix="kalshi_orderbook", norm_prefix="kalshi_orderbook",
            ts_keys=("recv_ms", "source_ts_ms"),
            liveness_ms=fcfg.kalshi_book_liveness_ms, decision_ms=fcfg.kalshi_book_decision_max_age_ms,
            required_for_feature_generation=True,
            feature_role="executable Kalshi YES/NO book — REQUIRED (no book => no executable example)",
            note="primary venue; public REST market data (no auth).",
        ),
        _source_entry(
            name="coinbase", enabled=True, implemented=True, required=False, used_in_features=True,
            raw_dir=raw, norm_dir=norm, raw_prefix="underlying_coinbase", norm_prefix="underlying_coinbase",
            price_keys=("price", "best_bid"),
            liveness_ms=fcfg.coinbase_liveness_ms, decision_ms=fcfg.coinbase_decision_max_age_ms,
            required_for_feature_generation=False,
            feature_role="PRIMARY BTC spot reference (returns / realized-vol / basis / distance-to-line)",
            note="BTC-USD spot ticker/trades (public REST). Ticker carries no bid/ask sizes.",
        ),
        _source_entry(
            name="binance", enabled=True, implemented=True, required=False, used_in_features=True,
            raw_dir=raw, norm_dir=norm,
            raw_prefix="underlying_binance_futures", norm_prefix="underlying_binance_futures",
            price_keys=("best_bid", "price"),
            liveness_ms=fcfg.binance_liveness_ms, decision_ms=fcfg.binance_decision_max_age_ms,
            required_for_feature_generation=False,
            feature_role="BTC perp (basis/microprice/OFI/queue-imbalance) + SPOT FALLBACK when Coinbase stale",
            can_serve_as_spot_fallback=True,
            note="BTCUSDT USDT-M bookTicker/trades (public REST); carries bid/ask sizes.",
        ),
        _source_entry(
            name="deribit", enabled=deribit_enabled,
            implemented=True, required=False, used_in_features=deribit_enabled,
            raw_dir=raw, norm_dir=norm, raw_prefix="deribit_btc", norm_prefix="deribit_btc",
            ts_keys=("recv_ms", "source_ts_ms"),
            price_keys=("deribit_index_price",),
            liveness_ms=fcfg.deribit_liveness_ms, decision_ms=fcfg.deribit_decision_max_age_ms,
            extra_value_keys=("deribit_dvol", "deribit_near_expiry_iv", "deribit_atm_iv",
                              "deribit_skew_proxy", "deribit_regime"),
            feature_role="OPTIONAL auxiliary vol/options regime, point-in-time joined "
                         "(deribit_*); not required for MVP",
            note=("optional auxiliary vol/options regime source; public REST; "
                  "point-in-time joined into feature rows with freshness flags."
                  if deribit_enabled else
                  "OPTIONAL and DISABLED by default (DERIBIT_ENABLED=false). "
                  "Not required for the Kalshi MVP."),
        ),
    ]
    by_name = {s["source"]: s for s in sources}
    # ----- Deribit: explicit, non-contradictory state (always non-fatal) -------
    # Deribit is IMPLEMENTED (the code exists) regardless of whether it is ENABLED.
    # Historical/leftover deribit_* rows may exist on disk even while disabled, so we
    # report config-enabled, historical-rows-present, freshness, and model-feature
    # SELECTION as distinct facts — never conflating "disabled" with "no data".
    de = by_name["deribit"]
    select_for_model = bool(getattr(deribit_cfg, "select_for_model_features", False))
    historical_rows_present = bool(
        de["latest_raw_ts_ms"] or de["latest_normalized_ts_ms"]
        or de["rows_today_raw"] or de["rows_today_normalized"])
    disabled_with_rows = bool(historical_rows_present and not deribit_enabled)
    de.update(
        enabled_by_config=deribit_enabled,
        optional=True,
        raw_rows_today=de["rows_today_raw"],
        normalized_rows_today=de["rows_today_normalized"],
        historical_rows_present=historical_rows_present,
        disabled_by_config_but_rows_present=disabled_with_rows,
        age_ms=de["data_age_ms"],
        # v3 feature rows always carry the deribit_* columns (None when disabled);
        # actual point-in-time VALUES are only joined when Deribit is enabled.
        feature_columns_present=True,
        joined_into_feature_rows=deribit_enabled,
        selected_for_model_features=select_for_model,
        include_in_model_features=bool(getattr(deribit_cfg, "include_in_model_features", False)),
    )
    # Looser point-in-time freshness threshold actually used by the join (not 5s).
    de["feature_freshness_threshold_ms"] = deribit_stale_ms
    if not deribit_enabled:
        de["status"] = ("disabled_historical_rows_present" if historical_rows_present else "disabled")
        if historical_rows_present:
            de["missing_reason"] = ("DERIBIT_DISABLED (historical rows present on disk; "
                                    "not selected for model candidate features unless enabled)")
            de["recommendation"] = (
                "Deribit DISABLED by config (DERIBIT_ENABLED=false), but historical/live rows are "
                "present. The deribit_* columns are NOT selected for model candidate features "
                f"(selected_for_model_features={select_for_model}). Optional; not required; does not "
                "gate readiness.")
        else:
            de["missing_reason"] = "DERIBIT_DISABLED (no recorded rows; optional, not required)"
            de["recommendation"] = ("Deribit disabled; no rows; optional; not required. Enable with "
                                    "DERIBIT_ENABLED=true to record + join optional vol/options context.")
    elif de["latest_normalized_ts_ms"] is None:
        de["status"] = "enabled_no_rows_yet"
        de["missing_reason"] = "DERIBIT_ENABLED_NO_ROWS_YET"
        de["recommendation"] = ("Deribit ENABLED but no rows recorded yet — run record-deribit or "
                                "add 'deribit' to --sources. Non-fatal; Kalshi pipeline continues.")
    elif de["stale"]:
        de["status"] = "enabled_stale"
        de["missing_reason"] = "DERIBIT_STALE"
        de["recommendation"] = (f"Deribit enabled but STALE ({de['stale_reason']}); feature rows flag "
                                "deribit_missing_reason/deribit_stale and continue. Kalshi MVP "
                                "continues without Deribit. Non-fatal.")
    else:
        de["status"] = "implemented"
        de["missing_reason"] = None
        de["recommendation"] = ("Deribit enabled and fresh — available for optional volatility/regime "
                                f"features, joined point-in-time (selected_for_model_features={select_for_model}).")
    cb, bn = by_name["coinbase"], by_name["binance"]
    # LIVENESS group ("is the underlying collector alive?"): at least one feed within
    # its loose liveness window. This is NOT sufficient for trading.
    underlying_ok = (not cb["liveness_stale"]) or (not bn["liveness_stale"])
    # DECISION group ("fresh enough to score / emit a PAPER_CANDIDATE?"): fallback-aware,
    # strict per-decision thresholds (Coinbase primary; Binance stands in only when
    # allowed + itself fresh). This is what trading must use — never the 60s liveness.
    und = resolve_underlying(coinbase_age_ms=cb["data_age_ms"], binance_age_ms=bn["data_age_ms"], fcfg=fcfg)
    underlying_decision_ok = und["fresh_for_paper_candidate"]
    if underlying_decision_ok and und["fallback_used"]:
        recommendation = (f"Underlying DECISION-fresh via FALLBACK: Coinbase decision-stale "
                          f"(age {cb['data_age_ms']}ms > {fcfg.coinbase_decision_max_age_ms}ms) but Binance fresh "
                          f"(age {bn['data_age_ms']}ms) -> use Binance mid as the spot reference.")
    elif underlying_decision_ok:
        recommendation = (f"Underlying DECISION-fresh: reference={und['reference_source']} "
                          f"(coinbase {cb['data_age_ms']}ms / binance {bn['data_age_ms']}ms vs "
                          f"{fcfg.coinbase_decision_max_age_ms}/{fcfg.binance_decision_max_age_ms}ms).")
    elif und["both_stale"]:
        recommendation = ("BOTH underlying feeds DECISION-stale -> NO PAPER_CANDIDATE (stale data must not "
                          "trade). Collectors may still be 'alive' under the 60s liveness window; that is "
                          "NOT good enough for a decision. Tighten polling / add WebSocket.")
    else:
        recommendation = (f"Underlying DECISION-stale ({und['reason']}); NO PAPER_CANDIDATE. "
                          "Liveness may be OK but decision freshness is not.")
    underlying = {
        "spot_primary": und["primary"],
        "spot_fallback": und["fallback"],
        # LIVENESS (collector alive?)
        "spot_primary_liveness_stale": cb["liveness_stale"],
        "spot_fallback_liveness_stale": bn["liveness_stale"],
        "underlying_ok": underlying_ok,                     # liveness group (back-compat)
        "underlying_liveness_ok": underlying_ok,
        # DECISION freshness (fresh enough to trade?)
        "coinbase_decision_stale": und["coinbase_decision_stale"],
        "binance_decision_stale": und["binance_decision_stale"],
        "both_decision_stale": und["both_stale"],
        "reference_source": und["reference_source"],
        "reference_age_ms": und["reference_age_ms"],
        "fallback_used": und["fallback_used"],
        "allow_binance_fallback": und["allow_binance_fallback"],
        "require_primary_for_entry": und["require_primary_for_entry"],
        "underlying_decision_ok": underlying_decision_ok,
        "fresh_for_paper_candidate": underlying_decision_ok,
        "decision_reason": und["reason"],
        # back-compat aliases (liveness-based)
        "spot_primary_stale": cb["stale"],
        "spot_fallback_stale": bn["stale"],
        "recommendation": recommendation,
        "note": ("LIVENESS (alive?) and DECISION freshness (trade-fresh?) are SEPARATE. Underlying "
                 f"decision thresholds: coinbase {fcfg.coinbase_decision_max_age_ms}ms / binance "
                 f"{fcfg.binance_decision_max_age_ms}ms (liveness {fcfg.coinbase_liveness_ms}ms). A feed can "
                 "be alive but too stale to trade; PAPER_CANDIDATE requires decision-freshness."),
    }
    n = config.notifications
    notifier = {
        "provider": ("pushover" if n.pushover_configured else "noop"),
        "pushover_enabled": n.pushover_enabled,
        "pushover_configured": n.pushover_configured,
        "note": "Pushover only when enabled AND both creds present; otherwise Noop. No tokens printed.",
    }
    return {"sources": sources, "underlying": underlying, "notifier": notifier,
            "assessed_at_ms": now_ms()}


def _frac(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def _stats(vals: list[int]) -> dict:
    if not vals:
        return {"n": 0, "min_ms": None, "max_ms": None, "mean_ms": None}
    return {"n": len(vals), "min_ms": min(vals), "max_ms": max(vals),
            "mean_ms": int(sum(vals) / len(vals))}


def source_freshness_smoke(config, *, series: str = "KXBTC15M", seconds: float = 60.0,
                           interval: float = 1.0, sleep: Callable[[float], None] = time.sleep) -> dict:
    """Sample source-health over ``seconds`` and report the DECISION-FRESH fraction.

    Read-only diagnostic that exposes whether each feed is recorded fast enough for a
    DECISION (not just alive). It repeatedly reads the latest recorded rows (no extra
    network) and aggregates, per source, the fraction of samples that were liveness-fresh
    vs decision-fresh, plus the underlying group's decision-ok fraction (with fallback).
    A high liveness fraction + low decision fraction == "alive but too stale to trade".
    """
    fcfg = config.freshness
    sources = ("kalshi", "coinbase", "binance")
    agg = {s: {"decision_fresh": 0, "liveness_fresh": 0, "ages": []} for s in sources}
    und_decision_ok = und_fallback_used = 0
    n = 0
    end = time.monotonic() + max(0.0, float(seconds))
    first = True
    while first or time.monotonic() < end:
        first = False
        h = assess_source_health(config)
        by = {s["source"]: s for s in h["sources"]}
        for src in sources:
            s = by.get(src, {})
            if s.get("data_age_ms") is not None:
                agg[src]["ages"].append(int(s["data_age_ms"]))
            if not s.get("decision_stale", True):
                agg[src]["decision_fresh"] += 1
            if not s.get("liveness_stale", True):
                agg[src]["liveness_fresh"] += 1
        u = h["underlying"]
        if u.get("underlying_decision_ok"):
            und_decision_ok += 1
        if u.get("fallback_used"):
            und_fallback_used += 1
        n += 1
        if time.monotonic() < end:
            sleep(max(0.2, float(interval)))

    per_source = {}
    for src in sources:
        a = agg[src]
        per_source[src] = {
            "decision_threshold_ms": _source_thresholds_for(fcfg, src)[1],
            "liveness_threshold_ms": _source_thresholds_for(fcfg, src)[0],
            "liveness_fresh_fraction": _frac(a["liveness_fresh"], n),
            "decision_fresh_fraction": _frac(a["decision_fresh"], n),
            "age": _stats(a["ages"]),
        }
    underlying_decision_fresh_fraction = _frac(und_decision_ok, n)
    # Verdict: the decision path needs the underlying decision-fresh most of the time.
    worst_decision = min((per_source[s]["decision_fresh_fraction"] for s in ("coinbase", "binance")),
                         default=0.0)
    if underlying_decision_fresh_fraction >= 0.8:
        verdict, rec = "DECISION_FRESH", "Underlying is decision-fresh — the runtime can score current data."
    elif per_source["coinbase"]["liveness_fresh_fraction"] >= 0.8 and worst_decision < 0.5:
        verdict, rec = ("ALIVE_BUT_DECISION_STALE",
                        "Feeds are ALIVE but too STALE for decisions. Poll Coinbase/Binance every 1-2s on the "
                        "decision path (lower --interval, fewer --max-markets, or a WebSocket feed). Do NOT "
                        "loosen the 5s decision threshold.")
    else:
        verdict, rec = ("FEEDS_DOWN_OR_SLOW",
                        "Underlying feeds are stale/absent — check the collector is running and recording "
                        "underlying_coinbase / underlying_binance_futures rows.")
    return {
        "series": series, "seconds": seconds, "samples": n, "interval": interval,
        "per_source": per_source,
        "underlying_decision_fresh_fraction": underlying_decision_fresh_fraction,
        "underlying_fallback_used_fraction": _frac(und_fallback_used, n),
        "verdict": verdict, "recommendation": rec,
        "note": "LIVENESS (alive?) != DECISION freshness (trade-fresh?). PAPER_CANDIDATE requires decision-fresh.",
    }


def _source_thresholds_for(fcfg, name: str) -> tuple[int, int]:
    from .freshness import _source_thresholds
    return _source_thresholds(fcfg, name)
