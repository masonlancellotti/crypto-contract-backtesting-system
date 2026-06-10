"""Run the paper decision loop and produce ledger entries.

Replays recorded normalized data point-in-time (no look-ahead), runs the
baseline model + gated decision layer, simulates non-midpoint fills for
PAPER_CANDIDATEs, and emits :class:`~btc5m.paper.ledger.LedgerEntry` rows. Joins
the OFFICIAL settlement label (when the window has completed) to compute realized
paper PnL — never reported as real profit.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from ..decision import DecisionConfig, evaluate_candidate
from ..decision.decision_layer import Decision
from ..models.baseline import BaselineInputs, BaselineModel
from ..timeutils import now_ms
from .ledger import LedgerEntry
from .simulate import realized_binary_pnl, simulate_paper_fill


def run_paper_decisions(
    config,
    *,
    asset: str = "BTC",
    duration: str = "5m",
    allow_uncalibrated: bool = False,
    sigma_override: Optional[float] = None,
    requested_size: float = 10.0,
    ref_ms: Optional[int] = None,
) -> tuple[list[LedgerEntry], dict]:
    """Replay -> model -> decision -> simulated fill -> ledger entries + stats."""
    from ..data.line_capture import load_line_records
    from ..data.polymarket_client import PolymarketClient, _slug_prefix
    from ..features.feature_builder import build_feature_row
    from ..features.replay import _ev_ts, _load_events
    from ..features.window import UnderlyingWindow
    from ..labels.settlement_backfill import load_label_rows, load_recorded_markets

    norm_dir = config.data_path() / "normalized"
    raw_dir = config.data_path() / "raw"
    prefix = _slug_prefix(asset, duration)
    now = ref_ms if ref_ms is not None else now_ms()

    markets = load_recorded_markets(raw_dir, slug_prefix=prefix)
    line_records = load_line_records(norm_dir)
    client = PolymarketClient(config)
    metas = {slug: client._parse_market(m, asset=asset) for slug, m in markets.items()}

    # OFFICIAL outcomes by slug (settlement-grade only).
    official_by_slug: dict[str, int] = {}
    for lr in load_label_rows(config.data_path() / "labels"):
        if lr.get("label_source_status") == "OFFICIAL" and lr.get("official_outcome") is not None:
            official_by_slug[lr.get("slug")] = lr["official_outcome"]

    book_events = [
        ev for ev in _load_events(norm_dir, "polymarket_book-*.jsonl")
        if (ev.get("slug") or "").startswith(prefix)
    ]
    book_events.sort(key=_ev_ts)
    underlying = sorted(
        _load_events(norm_dir, "underlying_coinbase-*.jsonl")
        + _load_events(norm_dir, "underlying_binance_futures-*.jsonl"),
        key=_ev_ts,
    )

    spot, perp = UnderlyingWindow("coinbase"), UnderlyingWindow("binance_futures")
    u_idx = 0
    latest_yes: dict[str, dict] = {}
    latest_no: dict[str, dict] = {}

    model = BaselineModel(config)
    dcfg = DecisionConfig(
        allow_uncalibrated=allow_uncalibrated,
        max_quote_age_ms=config.risk.max_quote_age_ms,
        fee_per_contract=0.0,
    )
    fee_bps = config.execution.taker_fee_bps

    entries: list[LedgerEntry] = []
    counts: Counter = Counter()
    fills = rejections = 0

    for be in book_events:
        as_of = _ev_ts(be)
        while u_idx < len(underlying) and _ev_ts(underlying[u_idx]) <= as_of:
            ue = underlying[u_idx]
            (spot if ue.get("source") == "coinbase" else perp).add_event(ue)
            u_idx += 1

        slug = be.get("slug")
        if be.get("outcome") == "YES":
            latest_yes[slug] = be
        elif be.get("outcome") == "NO":
            latest_no[slug] = be

        meta = metas.get(slug)
        row = build_feature_row(
            as_of_ms=as_of, slug=slug, condition_id=be.get("condition_id"),
            window_start_ms=(meta.window_start_ms if meta else be.get("window_start_ms")),
            expiry_ms=(meta.expiry_ms if meta else be.get("expiry_ms")),
            comparison=(meta.comparison.value if meta else "GTE"),
            yes_event=latest_yes.get(slug), no_event=latest_no.get(slug),
            line_record=line_records.get(slug), spot_window=spot, perp_window=perp,
            yes_token_id=(meta.yes_token_id if meta else None),
            no_token_id=(meta.no_token_id if meta else None),
            max_quote_age_ms=config.risk.max_quote_age_ms,
        )

        sigma = sigma_override or row.get("spot_rv_60s") or row.get("spot_rv_30s")
        out = model.predict_proba(BaselineInputs(
            reference_price=row.get("reference_price"), line=row.get("line_price"),
            seconds_to_expiry=row.get("seconds_to_expiry"), sigma_per_sqrt_s=sigma,
        ))
        line_status = row.get("line_source_status", "UNKNOWN")
        label_status = "OFFICIAL" if slug in official_by_slug else "UNKNOWN"
        cand = evaluate_candidate(
            row, out.p_yes, calibrated=out.calibration_ts_ms is not None,
            line_source_status=line_status, label_source_status=label_status, cfg=dcfg,
        )
        counts[cand["decision"]] += 1

        # Build a ledger entry for every actionable evaluation (candidate or
        # rejection). NO_ACTION with no side is skipped to keep the ledger lean.
        if cand["side"] is None and cand["decision"] == Decision.NO_ACTION.value:
            continue

        entry = LedgerEntry(
            timestamp_ms=as_of, slug=slug, condition_id=be.get("condition_id"),
            side=cand["side"], decision=cand["decision"],
            model_yes_probability=cand["model_yes_probability"],
            executable_price=cand["market_yes_ask"],
            estimated_costs=cand["estimated_costs"], net_edge=cand["net_edge"],
            reason_codes=cand["reason_codes"], line_source_status=line_status,
            label_source_status=label_status,
        )

        if cand["decision"] == Decision.PAPER_CANDIDATE.value:
            fill = simulate_paper_fill(
                cand["side"], latest_yes.get(slug), latest_no.get(slug),
                contract_id=str(be.get("condition_id") or slug or ""),
                requested_size=requested_size, taker_fee_bps=fee_bps,
            )
            entry.fill_status = fill.status
            entry.sim_price = fill.avg_price if fill.filled_size > 0 else None
            entry.sim_size = fill.filled_size
            entry.fees = fill.fees
            if fill.filled_size > 0:
                fills += 1
                if slug in official_by_slug:
                    entry.known_outcome = official_by_slug[slug]
                    entry.realized_pnl = realized_binary_pnl(
                        cand["side"], fill, official_by_slug[slug]
                    )
            else:
                rejections += 1
        else:
            entry.fill_status = "not_traded"
            rejections += 1

        entries.append(entry)

    stats = {
        "feature_rows": len(book_events),
        "decisions_by_state": dict(counts),
        "ledger_entries": len(entries),
        "paper_candidates": counts.get(Decision.PAPER_CANDIDATE.value, 0),
        "fills": fills,
        "rejections": rejections,
        "markets_seen": len(markets),
    }
    return entries, stats
