"""Cadence/source abstraction for Kalshi feature rows.

Two cadences feed the SAME downstream pipeline (dataset build, readiness, train,
calibrate, backtest, paper/decision):

* ``rest``  — the ~1-4 s REST collector's ``kalshi_feature_rows`` (DEFAULT; never
  degraded). Full feature schema (groups A-G, incl. Deribit + full microstructure).
* ``hires`` — the sub-second WebSocket ``kalshi_hires_joined_snapshots``, mapped by
  :func:`joined_to_feature_row` into the SAME feature-row schema so every existing
  consumer runs on second-level data unchanged. Hires rows carry a *subset* of the
  schema (best-ask book + spot/perp returns/vol/basis + source-health); fields that
  the joined stream does not carry (Kalshi bids/spreads/depth, CVD/OFI microstructure,
  Deribit, longer-horizon vols) are left ``None`` and surfaced by the existing
  missingness/source-health reporting — honest, not faked.

DATA IS READ-ONLY. Nothing here trades, places orders, or enables live submission.
Every adapted row carries ``no_live_orders=True`` / ``live_submission_allowed=False``.
"""

from __future__ import annotations

import math
from typing import Optional

REST = "rest"
HIRES = "hires"
VALID_SOURCES = (REST, HIRES)

# Aliases accepted on the CLI / API so callers can say "subsecond"/"ws" etc.
_ALIASES = {
    "rest": REST, "rest_cadence": REST, "low": REST, "lowres": REST, "low-res": REST,
    "hires": HIRES, "hi-res": HIRES, "highres": HIRES, "high-res": HIRES,
    "subsecond": HIRES, "sub-second": HIRES, "ws": HIRES, "websocket": HIRES,
}

# Default window duration (seconds) for the 15-minute crypto series, used only to
# derive context fields (fraction_window_elapsed / window_start_ms) for hires rows.
_DEFAULT_DURATION_S = 900


def normalize_source(source: Optional[str], *, config=None) -> str:
    """Resolve a source string (or ``None``) to ``REST``/``HIRES``.

    ``None`` defers to ``config.feature_source`` (set from the ``--feature-source``
    CLI flag) and finally to ``REST`` so the default path is byte-identical.
    """
    if source is None and config is not None:
        source = getattr(config, "feature_source", None)
    if source is None:
        return REST
    key = str(source).strip().lower()
    if key in VALID_SOURCES:
        return key
    if key in _ALIASES:
        return _ALIASES[key]
    raise ValueError(
        f"unknown feature source {source!r}; expected one of {VALID_SOURCES} "
        f"(aliases: subsecond/ws -> hires)")


def _duration_s(config) -> int:
    return int(getattr(getattr(config, "low_latency", None),
                       "market_duration_seconds", _DEFAULT_DURATION_S) or _DEFAULT_DURATION_S)


def joined_to_feature_row(j: dict, *, duration_s: int = _DEFAULT_DURATION_S) -> dict:
    """Map a joined WS snapshot (already enriched by ``load_joined``) to the
    ``kalshi_feature_rows`` schema. Derivable fields are filled; non-derivable
    fields are omitted (read as ``None`` by every consumer)."""
    as_of = j.get("as_of_ms")
    secs = j.get("seconds_to_close")
    tk = j.get("market_ticker")
    cb_mid = j.get("coinbase_mid")
    bn_mid = j.get("binance_mid")
    ref_start = j.get("reference_start_price")
    has_spot = bool(j.get("has_spot_feed"))
    has_perp = bool(j.get("has_perp_feed"))
    has_und = has_spot or has_perp
    yes_ask = j.get("yes_ask")
    no_ask = j.get("no_ask")
    has_ob = (yes_ask is not None) or (no_ask is not None)

    # contract/time context
    frac = None
    window_start_ms = None
    close_ms = j.get("close_ms")
    if secs is not None and duration_s > 0:
        frac = max(0.0, min(1.0, (duration_s - float(secs)) / float(duration_s)))
    if close_ms is not None:
        window_start_ms = int(close_ms) - duration_s * 1000

    # underlying distance-to-line (window-open reference) from spot
    distance_to_start = None
    if cb_mid is not None and ref_start is not None:
        distance_to_start = float(cb_mid) - float(ref_start)

    out = {
        # identifiers / context
        "market_ticker": tk,
        "series_ticker": (tk.split("-")[0] if tk else None),
        "as_of_ms": as_of,
        "close_ms": close_ms,
        "window_start_ms": window_start_ms,
        "status": "active",
        "feature_set_version": 3,
        # cadence provenance (new, non-training context)
        "feature_source": HIRES,
        "cadence": "subsecond",
        # A. contract / time
        "seconds_to_close": secs,
        "fraction_window_elapsed": frac,
        "distance_to_start": distance_to_start,
        "market_duration_seconds": duration_s,
        # B. kalshi orderbook (only best asks are carried by the joined stream)
        "yes_ask": yes_ask, "no_ask": no_ask,
        "yes_ask_size": j.get("yes_ask_size"), "no_ask_size": j.get("no_ask_size"),
        "quote_age_ms": j.get("kalshi_book_age_ms"),
        # C. underlying returns (5s/15s overlap the REST grid; sub-second extras kept)
        "spot_return_5s": j.get("spot_return_5s"),
        "spot_return_15s": j.get("spot_return_15s"),
        "spot_return_250ms": j.get("spot_return_250ms"),
        "spot_return_500ms": j.get("spot_return_500ms"),
        "spot_return_1s": j.get("spot_return_1s"),
        "spot_return_2s": j.get("spot_return_2s"),
        "perp_return_5s": j.get("perp_return_5s"),
        "perp_return_15s": j.get("perp_return_15s"),
        # D. underlying volatility (point-in-time realized vol from load_joined)
        "realized_vol_60s": j.get("realized_vol_60s"),
        # E. underlying microstructure (spot/perp basis carried; CVD/OFI not in WS join)
        "spot_perp_basis": j.get("basis"),
        # F. deribit — never present on the WS join: keep it explicitly excluded
        "deribit_available": False,
        "deribit_stale": True,
        "has_deribit": False,
        # G. source-health / missingness
        "coinbase_mid": cb_mid, "binance_mid": bn_mid,
        "coinbase_age_ms": j.get("coinbase_age_ms"), "binance_age_ms": j.get("binance_age_ms"),
        "coinbase_stale": bool(j.get("coinbase_stale")),
        "binance_stale": bool(j.get("binance_stale")),
        "has_spot_feed": has_spot, "has_perp_feed": has_perp,
        # presence flags consumed by the gates / dataset builder
        "has_orderbook": has_ob,
        "has_underlying": has_und,
        "has_start_reference": ref_start is not None,
        "reference_start_price": ref_start,
        "book_ok": bool(has_ob and (secs is not None and secs > 0)),
        # read-only safety markers (mirror the producer)
        "no_live_orders": True,
        "live_submission_allowed": False,
    }
    return out


def load_feature_rows(
    config,
    *,
    source: Optional[str] = None,
    date=None,
    start_date=None,
    end_date=None,
) -> list[dict]:
    """Load feature rows for the requested cadence.

    REST (default) -> the recorded ``kalshi_feature_rows`` (unchanged behaviour).
    HIRES          -> ``kalshi_hires_joined_snapshots`` adapted to the feature-row
                      schema. Date filters apply to the hires path only (the REST
                      glob already spans recorded days).
    """
    src = normalize_source(source, config=config)
    if src == HIRES:
        from .reprice_lag_hires import load_joined
        dur = _duration_s(config)
        jr = load_joined(config, date=date, start_date=start_date, end_date=end_date)
        return [joined_to_feature_row(r, duration_s=dur) for r in jr["rows"]]
    # REST default — reuse the canonical loader so behaviour never drifts.
    from .readiness import _event, _load_glob
    return [_event(r) for r in _load_glob(config.data_path() / "features",
                                          "kalshi_feature_rows*.jsonl")]


def latest_hires_feature_rows(config, *, series: str = "KXBTC15M") -> list[dict]:
    """Freshest joined WS snapshot per ticker, adapted to the feature-row schema.

    Self-contained (does NOT call back into ``paper_runtime``) so the paper/decision
    path can delegate here for ``hires`` without recursion. Still a *collection* row
    per market — callers MUST apply their decision-eligibility filter before scoring.
    """
    from .reprice_lag_hires import _read_rows, joined_files
    dur = _duration_s(config)
    files = joined_files(config)
    latest: dict = {}
    # newest files last; a couple of recent segments span the active set.
    for path in files[-3:]:
        for o in _read_rows(path):
            tk = o.get("market_ticker")
            as_of = o.get("as_of_ms")
            if tk is None or as_of is None:
                continue
            if series and not str(tk).startswith(series):
                continue
            prev = latest.get(tk)
            if prev is None or as_of >= prev.get("as_of_ms", -math.inf):
                latest[tk] = o
    return [joined_to_feature_row(o, duration_s=dur) for o in latest.values()]


def latest_feature_rows_for_source(
    config, *, source: Optional[str] = None, series: str = "KXBTC15M", lines: int = 4000,
) -> list[dict]:
    """Freshest row per ticker for the live/paper decision path.

    REST  -> the existing tail-read of the newest feature file.
    HIRES -> the freshest joined snapshot per ticker (sub-second).
    """
    src = normalize_source(source, config=config)
    if src == HIRES:
        return latest_hires_feature_rows(config, series=series)
    from .paper_runtime import latest_feature_rows
    return latest_feature_rows(config, series=series, lines=lines)
