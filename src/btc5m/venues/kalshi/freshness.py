"""Source freshness — LIVENESS vs DECISION freshness, explicit and strict.

The single source of truth for "is this data fresh enough?". A collector can be
ALIVE (a row within the loose liveness window, ~60s) while its data is TOO STALE to
trade on (older than the strict per-decision window, ~1s book / ~5s underlying).
These two are computed from the SAME measured age but compared to DIFFERENT
thresholds — never conflated.

Key outputs per source: ``liveness_*`` (alive?), ``decision_*`` (trade-fresh?), and
``fresh_for_collection / fresh_for_decision / fresh_for_training /
fresh_for_paper_candidate``. The underlying group adds explicit, config-driven
Binance-fallback resolution (Coinbase primary; Binance stands in only when allowed
and itself fresh). ``paper_candidate_freshness`` is the strict gate the paper
runtime calls so STALE data can NEVER produce a PAPER_CANDIDATE.
"""

from __future__ import annotations

from typing import Optional

# Reason codes (decision-freshness rejections).
BOOK_DECISION_STALE = "BOOK_DECISION_STALE"
UNDERLYING_DECISION_STALE = "UNDERLYING_DECISION_STALE"
UNDERLYING_BOTH_STALE = "UNDERLYING_BOTH_STALE"
UNDERLYING_PRIMARY_STALE = "UNDERLYING_PRIMARY_STALE"
FEATURE_ROW_STALE = "FEATURE_ROW_STALE"


def _stale(age_ms: Optional[int], threshold_ms: int) -> bool:
    """Stale iff there is no age (no data) OR the age exceeds the threshold."""
    return age_ms is None or age_ms > threshold_ms


def source_freshness(name: str, age_ms: Optional[int], *, liveness_ms: int,
                     decision_ms: int, training_ms: Optional[int] = None) -> dict:
    """Liveness vs decision freshness for ONE source from a single measured age.

    ``liveness_*`` use the loose threshold ("is the collector alive?"); ``decision_*``
    use the strict threshold ("fresh enough to score / emit a candidate?"). Training
    freshness defaults to the decision threshold (features are point-in-time)."""
    training_ms = decision_ms if training_ms is None else training_ms
    has_data = age_ms is not None
    liveness_stale = _stale(age_ms, liveness_ms) if has_data else True
    decision_stale = _stale(age_ms, decision_ms)
    training_stale = _stale(age_ms, training_ms)
    return {
        "source": name,
        "liveness_age_ms": age_ms,
        "liveness_threshold_ms": liveness_ms,
        "liveness_stale": liveness_stale,
        "decision_age_ms": age_ms,
        "decision_threshold_ms": decision_ms,
        "decision_stale": decision_stale,
        "fresh_for_collection": bool(has_data and not liveness_stale),
        "fresh_for_decision": bool(has_data and not decision_stale),
        "fresh_for_training": bool(has_data and not training_stale),
        "fresh_for_paper_candidate": bool(has_data and not decision_stale),
    }


def _source_thresholds(fcfg, name: str) -> tuple[int, int]:
    """(liveness_ms, decision_ms) for a named source from FreshnessConfig."""
    n = (name or "").lower()
    if n == "kalshi":
        return fcfg.kalshi_book_liveness_ms, fcfg.kalshi_book_decision_max_age_ms
    if n in ("coinbase", "coinbase_spot", "cb"):
        return fcfg.coinbase_liveness_ms, fcfg.coinbase_decision_max_age_ms
    if n in ("binance", "binance_futures", "binance_perp"):
        return fcfg.binance_liveness_ms, fcfg.binance_decision_max_age_ms
    if n == "deribit":
        return fcfg.deribit_liveness_ms, fcfg.deribit_decision_max_age_ms
    return fcfg.coinbase_liveness_ms, fcfg.coinbase_decision_max_age_ms


def source_freshness_from_config(fcfg, name: str, age_ms: Optional[int]) -> dict:
    liveness_ms, decision_ms = _source_thresholds(fcfg, name)
    return source_freshness(name, age_ms, liveness_ms=liveness_ms, decision_ms=decision_ms)


def resolve_underlying(*, coinbase_age_ms: Optional[int], binance_age_ms: Optional[int],
                       fcfg) -> dict:
    """Fallback-aware underlying DECISION freshness (Coinbase primary, Binance fallback).

    Coinbase is the primary BTC reference; Binance stands in ONLY when Coinbase is
    decision-stale AND fallback is allowed AND Binance is itself decision-fresh. If
    ``underlying_require_primary_for_entry`` is set, only Coinbase counts. If both
    feeds are stale (and ``underlying_reject_if_both_stale``), the underlying is stale.
    """
    primary = (fcfg.underlying_primary or "coinbase").lower()
    fallback = (fcfg.underlying_fallback or "binance").lower()
    coinbase_stale = _stale(coinbase_age_ms, fcfg.coinbase_decision_max_age_ms)
    binance_stale = _stale(binance_age_ms, fcfg.binance_decision_max_age_ms)

    def age_of(src):
        return coinbase_age_ms if src == "coinbase" else binance_age_ms

    def stale_of(src):
        return coinbase_stale if src == "coinbase" else binance_stale

    primary_stale = stale_of(primary)
    fallback_stale = stale_of(fallback)
    both_stale = coinbase_stale and binance_stale
    allow_fb = bool(fcfg.underlying_allow_binance_fallback)
    require_primary = bool(fcfg.underlying_require_primary_for_entry)

    if require_primary:
        reference, ref_age, decision_stale, fallback_used = primary, age_of(primary), primary_stale, False
        reason = "PRIMARY_REQUIRED"
    elif not primary_stale:
        reference, ref_age, decision_stale, fallback_used = primary, age_of(primary), False, False
        reason = "PRIMARY_FRESH"
    elif allow_fb and not fallback_stale:
        reference, ref_age, decision_stale, fallback_used = fallback, age_of(fallback), False, True
        reason = "FALLBACK_USED_PRIMARY_STALE"
    else:
        reference, ref_age, decision_stale, fallback_used = primary, age_of(primary), True, False
        reason = ("BOTH_STALE" if both_stale else
                  ("PRIMARY_STALE_FALLBACK_DISABLED" if not allow_fb else "PRIMARY_STALE_FALLBACK_ALSO_STALE"))

    if fcfg.underlying_reject_if_both_stale and both_stale:
        decision_stale = True
        reason = "BOTH_STALE"

    return {
        "reference_source": reference,
        "reference_age_ms": ref_age,
        "coinbase_age_ms": coinbase_age_ms,
        "binance_age_ms": binance_age_ms,
        "coinbase_decision_stale": coinbase_stale,
        "binance_decision_stale": binance_stale,
        "primary": primary,
        "fallback": fallback,
        "primary_stale": primary_stale,
        "fallback_stale": fallback_stale,
        "both_stale": both_stale,
        "fallback_used": fallback_used,
        "allow_binance_fallback": allow_fb,
        "require_primary_for_entry": require_primary,
        "underlying_decision_stale": bool(decision_stale),
        "fresh_for_paper_candidate": (not decision_stale),
        "reason": reason,
    }


def paper_candidate_freshness(*, book_age_ms: Optional[int], coinbase_age_ms: Optional[int],
                              binance_age_ms: Optional[int], fcfg,
                              feature_row_age_ms: Optional[int] = None) -> dict:
    """Strict per-decision freshness gate for PAPER_CANDIDATE. Returns ``ok`` + reasons.

    Honors the ``reject_paper_if_*`` toggles. ``feature_row_age_ms`` is the LIVE
    now-vs-as_of age (only meaningful on the hot path); pass None for historical
    replay so a recorded snapshot isn't rejected for being old-in-wall-clock.
    """
    book_stale = _stale(book_age_ms, fcfg.kalshi_book_decision_max_age_ms)
    und = resolve_underlying(coinbase_age_ms=coinbase_age_ms, binance_age_ms=binance_age_ms, fcfg=fcfg)
    feature_row_stale = bool(feature_row_age_ms is not None
                             and feature_row_age_ms > fcfg.feature_row_max_age_ms)

    reasons: list[str] = []
    if fcfg.reject_paper_if_book_stale and book_stale:
        reasons.append(BOOK_DECISION_STALE)
    if fcfg.reject_paper_if_underlying_stale and und["underlying_decision_stale"]:
        if und["both_stale"]:
            reasons.append(UNDERLYING_BOTH_STALE)
        elif und["require_primary_for_entry"] and und["primary_stale"]:
            reasons.append(UNDERLYING_PRIMARY_STALE)
        else:
            reasons.append(UNDERLYING_DECISION_STALE)
    if fcfg.reject_paper_if_feature_row_stale and feature_row_stale:
        reasons.append(FEATURE_ROW_STALE)

    ok = not reasons
    return {
        "ok": ok,
        "fresh_for_paper_candidate": ok,
        "reasons": reasons,
        "book_age_ms": book_age_ms,
        "book_decision_threshold_ms": fcfg.kalshi_book_decision_max_age_ms,
        "book_decision_stale": book_stale,
        "feature_row_age_ms": feature_row_age_ms,
        "feature_row_max_age_ms": fcfg.feature_row_max_age_ms,
        "feature_row_stale": feature_row_stale,
        "underlying": und,
    }
