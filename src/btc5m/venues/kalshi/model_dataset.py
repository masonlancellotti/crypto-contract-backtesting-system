"""Kalshi model-dataset builder.

Joins point-in-time Kalshi feature rows to **feature-backed OFFICIAL** labels
(orphan labels — official results with no features — can never enter), with NO
look-ahead (feature ``as_of_ms`` must be < market ``close_ms``), preserves IDs +
timestamps, applies source-health/missingness filters, and reports every dropped
row with a reason. Output is a flat model-ready table (JSONL/CSV; parquet only if
pandas/pyarrow are present, else a safe fallback) plus metadata + missingness +
leakage-exclusion + gate reports. Building NEVER trades and NEVER trains.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from typing import Optional

from .book_freshness import effective_book_age
from .feature_schema import (
    LEAKAGE_EXCLUDED, MODEL_SCHEMA_VERSION, SCHEMA, deribit_candidate_feature_names,
    schema_json, training_feature_names,
)
from .labels_audit import dedup_labels, load_label_rows
from .readiness import (
    MIN_BACKTEST_WINDOWS, MIN_TRAIN_ROWS, MIN_TRAIN_WINDOWS,
    _event, _load_glob, feature_row_usable,
)

# Every schema feature name carried on each model row (context + training inputs).
_ALL_FEATURE_NAMES = [s.name for s in SCHEMA]


def _load_feature_rows(config) -> list[dict]:
    return [_event(r) for r in _load_glob(config.data_path() / "features", "kalshi_feature_rows*.jsonl")]


def _official_labels(config) -> dict[str, dict]:
    labels = dedup_labels(load_label_rows(config))
    return {tk: lr for tk, lr in labels.items()
            if lr.get("label_source_status") == "OFFICIAL" and lr.get("label_yes_resolved") is not None}


def build_model_dataset(
    config,
    *,
    series: str = "KXBTC15M",
    include_deribit: str = "auto",       # "true" | "false" | "auto"
    strict: bool = False,
    feature_version: str = "all",        # "all" (v1/v2/v3 coexist) | "latest" (v3 only)
) -> dict:
    """Build the model-ready dataset (in memory) + full accounting. No training."""
    duration_ms = int(getattr(getattr(config, "low_latency", None), "market_duration_seconds", 900)) * 1000
    feats = _load_feature_rows(config)
    official = _official_labels(config)

    counts = {
        "total_feature_rows": len(feats),
        "feature_rows_with_orderbook": 0,
        "feature_rows_with_underlying": 0,
        "feature_rows_with_start_reference": 0,
        "feature_rows_joined_to_official": 0,
        "rows_rejected_missing_book": 0,
        "rows_rejected_missing_underlying": 0,
        "rows_rejected_missing_label": 0,
        "rows_rejected_window_closed_or_bad_book": 0,
        "rows_rejected_stale_source": 0,
        "rows_rejected_old_feature_version": 0,
        "final_model_rows": 0,
    }
    rows: list[dict] = []
    windows: set[str] = set()
    version_counts: dict = {}

    for r in feats:
        has_ob = bool(r.get("has_orderbook"))
        has_und = bool(r.get("has_underlying"))
        has_start = bool(r.get("has_start_reference"))
        if has_ob:
            counts["feature_rows_with_orderbook"] += 1
        if has_und:
            counts["feature_rows_with_underlying"] += 1
        if has_start:
            counts["feature_rows_with_start_reference"] += 1

        tk = r.get("market_ticker")
        # ---- usability + no-lookahead gating, each rejection counted with a reason
        if not has_ob:
            counts["rows_rejected_missing_book"] += 1
            continue
        if not has_und:
            counts["rows_rejected_missing_underlying"] += 1
            continue
        if not feature_row_usable(r):
            counts["rows_rejected_window_closed_or_bad_book"] += 1
            continue
        if tk not in official:
            counts["rows_rejected_missing_label"] += 1
            continue
        counts["feature_rows_joined_to_official"] += 1

        close_ms = r.get("close_ms")
        as_of = r.get("as_of_ms")
        if close_ms is not None and as_of is not None and not (as_of < close_ms):
            counts["rows_rejected_window_closed_or_bad_book"] += 1
            continue

        fsv = r.get("feature_set_version")
        if feature_version == "latest" and fsv != 3:
            counts["rows_rejected_old_feature_version"] += 1
            continue

        # strict source-health: require at least one fresh underlying feed.
        if strict and r.get("coinbase_stale") and r.get("binance_stale"):
            counts["rows_rejected_stale_source"] += 1
            continue

        version_counts[str(fsv)] = version_counts.get(str(fsv), 0) + 1
        rows.append(_model_row(r, official[tk], duration_ms=duration_ms))
        if tk:
            windows.add(tk)

    counts["final_model_rows"] = len(rows)
    distinct_windows = len(windows)

    # ---- Deribit: distinguish COLUMN PRESENCE from CANDIDATE-FEATURE SELECTION ----
    # A disabled/leftover Deribit may leave deribit_* columns on historical rows, but
    # those columns must NOT silently enter the model. Selection is config-driven
    # (DERIBIT_INCLUDE_IN_MODEL_FEATURES, gated by select_for_model_features) unless
    # the operator forces it via --include-deribit true/false for inspection.
    de_block = _deribit_block(config, rows, include_deribit)
    deribit_selected = de_block["selected_for_model_features"]

    training_features = training_feature_names()
    if not deribit_selected:
        deribit_cols = set(deribit_candidate_feature_names())
        training_features = [f for f in training_features if f not in deribit_cols]

    missingness = _missingness(rows)
    gate = _gate(distinct_windows, len(rows))
    return {
        "series": series,
        "rows": rows,
        "counts": counts,
        "distinct_windows": distinct_windows,
        "missingness": missingness,
        "feature_version_counts": version_counts,
        "model_schema_version": MODEL_SCHEMA_VERSION,
        # Back-compat key: now means "Deribit SELECTED for the model candidate feature
        # group" (not mere column presence). EXCLUDED_BY_CONFIG when disabled/not-included.
        "deribit_included": deribit_selected,
        "deribit": de_block,
        "strict": strict,
        "feature_version_filter": feature_version,
        "gate": gate,
        "training_features": training_features,
        "leakage_excluded": sorted(LEAKAGE_EXCLUDED),
    }


def _deribit_block(config, rows: list[dict], include_deribit: str) -> dict:
    """Distinguish Deribit column presence, config state, and model selection.

    ``include_deribit`` is the operator override: "auto" defers to the config's
    ``select_for_model_features`` (the honest default); "true"/"false" force the
    candidate-group decision for inspection only. Column presence never auto-selects.
    """
    de_cfg = getattr(config, "deribit", None)
    de_enabled = bool(getattr(de_cfg, "enabled", False))
    de_include_flag = bool(getattr(de_cfg, "include_in_model_features", False))
    de_select_cfg = bool(getattr(de_cfg, "select_for_model_features", False))

    n = len(rows) or 1
    columns_present = any("deribit_dvol" in row for row in rows)
    available = sum(1 for row in rows if row.get("has_deribit"))
    stale = sum(1 for row in rows if row.get("deribit_stale"))
    used = sum(1 for row in rows if row.get("has_deribit") and not row.get("deribit_stale"))

    if include_deribit == "true":
        selected = True
    elif include_deribit == "false":
        selected = False
    else:  # auto -> config-driven (NOT mere column presence)
        selected = de_select_cfg

    if not selected:
        status = "EXCLUDED_BY_CONFIG"
    elif available == 0:
        status = "UNAVAILABLE"
    elif used == 0:
        status = "STALE"
    else:
        status = "INCLUDED"

    candidate_cols = deribit_candidate_feature_names()
    return {
        "columns_present": columns_present,
        "enabled_in_config": de_enabled,
        "include_in_model_features": de_include_flag,
        "allow_historical_features_when_disabled":
            bool(getattr(de_cfg, "allow_historical_features_when_disabled", False)),
        "selected_for_model_features": selected,
        "include_deribit_override": include_deribit,
        "rows_total": len(rows),
        "rows_with_deribit_columns": available,
        "rows_with_deribit_used": used,
        "rows_with_deribit_stale": stale,
        "fraction_used": round(used / n, 4),
        "candidate_feature_group_status": status,
        "selected_candidate_feature_count": (len(candidate_cols) if selected else 0),
        "candidate_feature_columns": candidate_cols,
        "note": ("Column presence != candidate-feature selection. Disabled/leftover Deribit "
                 "columns are never silently fed to the model; selection requires "
                 "DERIBIT_INCLUDE_IN_MODEL_FEATURES (and an enabled source, or an explicit "
                 "allow-historical opt-in)."),
    }


def _model_row(r: dict, label: dict, *, duration_ms: int) -> dict:
    close_ms = r.get("close_ms")
    as_of = r.get("as_of_ms")
    secs = r.get("seconds_to_close")
    open_ms = r.get("window_start_ms")
    if open_ms is None and close_ms is not None:
        open_ms = close_ms - duration_ms
    frac_elapsed = None
    if secs is not None and duration_ms > 0:
        frac_elapsed = max(0.0, min(1.0, (duration_ms / 1000.0 - secs) / (duration_ms / 1000.0)))
    book_age = effective_book_age(r, as_of_ms=as_of)

    row: dict = {
        "row_id": f"{r.get('market_ticker')}@{as_of}",
        "series": r.get("series_ticker"),
        "ticker": r.get("market_ticker"),
        "market_open_ts_ms": open_ms,
        "market_close_ts_ms": close_ms,
        "as_of_ts_ms": as_of,
        "seconds_to_close": secs,
        "fraction_window_elapsed": frac_elapsed,
        "label_yes_resolved": int(label.get("label_yes_resolved")),
        "label_source": "OFFICIAL",
        "model_schema_version": MODEL_SCHEMA_VERSION,
        "feature_set_version": r.get("feature_set_version"),
        "has_kalshi_book": bool(r.get("has_orderbook")),
        "has_underlying": bool(r.get("has_underlying")),
        "has_start_reference": bool(r.get("has_start_reference")),
        "has_deribit": bool(r.get("deribit_available")),
        # Point-in-time execution context (known at as_of; NOT training features /
        # NOT leakage) — carried so the executable backtest can gate + settle.
        "book_ok": bool(r.get("book_ok")),
        "reference_start_price": r.get("reference_start_price"),
        "reference_start_price_source": r.get("reference_start_price_source"),
        "reference_start_price_ts_ms": r.get("reference_start_price_ts_ms"),
        "reference_start_price_age_ms": r.get("reference_start_price_age_ms"),
        "reference_start_price_method": r.get("reference_start_price_method"),
        "reference_start_price_confidence": r.get("reference_start_price_confidence"),
        "reference_start_price_source_status": r.get("reference_start_price_source_status"),
        "reference_missing_reason": r.get("reference_missing_reason"),
        "yes_ask_size": r.get("yes_ask_size"),
        "no_ask_size": r.get("no_ask_size"),
        "coinbase_stale": bool(r.get("coinbase_stale")),
        "binance_stale": bool(r.get("binance_stale")),
        "deribit_stale": r.get("deribit_stale"),
        "quote_age_ms": r.get("quote_age_ms"),
        "book_age_ms": book_age.get("book_age_ms"),
        "book_age_basis": book_age.get("book_age_basis"),
        "book_age_method": book_age.get("book_age_method"),
        "book_age_source": book_age.get("book_age_source"),
        "book_age_confidence": book_age.get("book_age_confidence"),
        "book_recv_ms": book_age.get("book_recv_ms"),
        "book_source_ts_ms": book_age.get("book_source_ts_ms"),
        # Per-source underlying ages (within-row, at as_of) for fallback-aware decision
        # freshness; underlying_age_ms keeps the legacy MAX for back-compat.
        "coinbase_feed_age_ms": r.get("coinbase_feed_age_ms"),
        "binance_feed_age_ms": r.get("binance_feed_age_ms"),
        "underlying_age_ms": _max_age(r.get("coinbase_feed_age_ms"), r.get("binance_feed_age_ms")),
        "deribit_age_ms": r.get("deribit_age_ms"),
    }
    # Carry every schema feature value (context + training inputs). fraction is
    # computed above; don't overwrite it from the (absent) raw row key.
    for name in _ALL_FEATURE_NAMES:
        if name == "fraction_window_elapsed":
            continue
        row[name] = r.get(name)
    return row


def _max_age(a, b):
    vals = [v for v in (a, b) if v is not None]
    return max(vals) if vals else None


def _missingness(rows: list[dict]) -> dict:
    n = len(rows) or 1
    out = {}
    for name in training_feature_names():
        missing = sum(1 for row in rows if row.get(name) is None)
        out[name] = round(missing / n, 4)
    return out


def _gate(distinct_windows: int, n_rows: int) -> dict:
    training_ready = distinct_windows >= MIN_TRAIN_WINDOWS and n_rows >= MIN_TRAIN_ROWS
    return {
        "gate_windows": distinct_windows,
        "rows": n_rows,
        "backtest_gate_threshold": MIN_BACKTEST_WINDOWS,
        "train_gate_threshold": MIN_TRAIN_WINDOWS,
        "train_gate_min_rows": MIN_TRAIN_ROWS,
        "backtest_allowed": distinct_windows >= MIN_BACKTEST_WINDOWS,
        "training_ready": training_ready,
        "windows_remaining_to_backtest": max(0, MIN_BACKTEST_WINDOWS - distinct_windows),
        "windows_remaining_to_train": max(0, MIN_TRAIN_WINDOWS - distinct_windows),
        "status": "TRAINING_READY" if training_ready else "NOT_TRAINING_READY",
    }


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _write_table(path: str, rows: list[dict], fmt: str) -> None:
    if fmt == "csv":
        _write_csv(path, rows)
    elif fmt == "parquet":
        _write_parquet(path, rows)
    else:
        _write_jsonl(path, rows)


def write_dataset(config, dataset: dict, *, fmt: str = "jsonl",
                  output: Optional[str] = None, update_latest: bool = True,
                  staged: bool = False) -> dict:
    """Write the dataset file + metadata + feature-schema + report. Returns paths.

    ``staged=True`` writes everything under ``data/models/staged/`` and NEVER touches
    the active ``kalshi_model_dataset_latest.*`` / ``kalshi_feature_schema.json``
    pointers (forces ``update_latest=False``). ``update_latest=False`` (non-staged)
    writes a timestamped dataset + a timestamped feature schema but leaves the active
    latest pointers untouched. This prevents a staged build from silently becoming
    the dataset the rest of the pipeline reads.
    """
    active = config.data_path() / "models"
    active.mkdir(parents=True, exist_ok=True)
    if staged:
        update_latest = False
        d = active / "staged"
        d.mkdir(parents=True, exist_ok=True)
    else:
        d = active
    reports = config.reports_path() / "models"
    reports.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    rows = dataset["rows"]

    fmt = fmt.lower()
    if fmt == "parquet" and not _parquet_available():
        fmt = "jsonl"  # safe fallback; never add a fragile dependency
        dataset["parquet_fallback"] = True

    base = output or str(d / f"kalshi_dataset_{stamp}.{fmt}")
    if not base.endswith(f".{fmt}"):
        base = f"{base}.{fmt}"
    _write_table(base, rows, fmt)

    # Active "latest" pointer — ONLY when explicitly updating latest (never when staged).
    latest = None
    if update_latest:
        latest = str(active / f"kalshi_model_dataset_latest.{fmt}")
        _write_table(latest, rows, fmt)

    meta_path = base.rsplit(".", 1)[0] + ".metadata.json"
    metadata = {
        "series": dataset["series"], "created_at_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
        "format": fmt, "n_rows": len(rows), "distinct_windows": dataset["distinct_windows"],
        "model_schema_version": dataset["model_schema_version"],
        "feature_version_counts": dataset["feature_version_counts"],
        "deribit_included": dataset["deribit_included"], "deribit": dataset["deribit"],
        "strict": dataset["strict"], "staged": bool(staged), "update_latest": bool(update_latest),
        "feature_version_filter": dataset["feature_version_filter"],
        "counts": dataset["counts"], "gate": dataset["gate"],
        "training_features": dataset["training_features"],
        "leakage_excluded": dataset["leakage_excluded"],
        "status": dataset["gate"]["status"],
    }
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2)
    # Feature schema: overwrite the ACTIVE pointer only when updating latest; otherwise
    # write a timestamped/staged schema next to the dataset (never clobber active).
    if update_latest:
        schema_path = str(active / "kalshi_feature_schema.json")
    else:
        schema_path = str(d / f"kalshi_feature_schema_{stamp}.json")
    with open(schema_path, "w", encoding="utf-8") as fh:
        json.dump(schema_json(), fh, indent=2)
    report_path = str(reports / f"kalshi_dataset_report_{stamp}.md")
    _write_report(report_path, dataset, base)
    return {"dataset_file": base, "latest_file": latest, "metadata_file": meta_path,
            "schema_file": schema_path, "report_file": report_path, "format": fmt,
            "staged": bool(staged), "update_latest": bool(update_latest)}


def _parquet_available() -> bool:
    try:
        import pandas  # noqa: F401
        import pyarrow  # noqa: F401
        return True
    except Exception:
        return False


def _write_jsonl(path: str, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _write_csv(path: str, rows: list[dict]) -> None:
    if not rows:
        open(path, "w", encoding="utf-8").close()
        return
    cols = list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for row in rows:
            w.writerow({c: row.get(c) for c in cols})


def _write_parquet(path: str, rows: list[dict]) -> None:  # pragma: no cover - deps absent
    import pandas as pd
    pd.DataFrame(rows).to_parquet(path, index=False)


def _write_report(path: str, dataset: dict, dataset_file: str) -> None:
    c = dataset["counts"]
    g = dataset["gate"]
    lines = [
        f"# Kalshi model dataset report — {dataset['series']}", "",
        f"- status: **{g['status']}**",
        f"- dataset_file: `{dataset_file}`",
        f"- final_model_rows: {c['final_model_rows']}",
        f"- distinct_windows: {dataset['distinct_windows']}",
        f"- gate_windows: {g['gate_windows']} / train {g['train_gate_threshold']} "
        f"(backtest {g['backtest_gate_threshold']})",
        f"- windows_remaining_to_backtest: {g['windows_remaining_to_backtest']}",
        f"- windows_remaining_to_train: {g['windows_remaining_to_train']}",
        f"- feature_set_version_counts: {dataset['feature_version_counts']}",
        f"- deribit_included (selected for model): {dataset['deribit_included']}  strict: {dataset['strict']}",
        "", "## Row accounting (every drop has a reason)",
    ]
    for k, v in c.items():
        lines.append(f"- {k}: {v}")
    de = dataset.get("deribit") or {}
    if de:
        lines += ["", "## Deribit (OPTIONAL; column presence != candidate-feature selection)",
                  f"- candidate_feature_group_status: **{de.get('candidate_feature_group_status')}**",
                  f"- columns_present: {de.get('columns_present')}",
                  f"- enabled_in_config: {de.get('enabled_in_config')}",
                  f"- include_in_model_features: {de.get('include_in_model_features')}",
                  f"- selected_for_model_features: {de.get('selected_for_model_features')}",
                  f"- rows_with_deribit_used: {de.get('rows_with_deribit_used')}/{de.get('rows_total')} "
                  f"(stale {de.get('rows_with_deribit_stale')}, fraction_used {de.get('fraction_used')})",
                  f"- selected_candidate_feature_count: {de.get('selected_candidate_feature_count')}",
                  f"- {de.get('note')}"]
    lines += ["", "## Training-feature missingness (fraction None over final rows)"]
    for name, frac in dataset["missingness"].items():
        flag = "  <-- always missing" if frac >= 0.999 else ("  <-- often missing" if frac >= 0.5 else "")
        lines.append(f"- {name}: {frac}{flag}")
    lines += ["", "## Leakage exclusions (never in training matrix)",
              f"- {', '.join(dataset['leakage_excluded'])}",
              "", "## Safety",
              "- OFFICIAL feature-backed labels only; orphan labels excluded.",
              "- Windows (not rows) drive the gate; purge/embargo applied at split time.",
              "- Hard Up/Down class is diagnostic only; no PAPER_CANDIDATE; live disabled."]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
