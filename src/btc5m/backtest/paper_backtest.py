"""Minimum executable backtest/paper path — gated by data readiness.

If there are not enough usable, OFFICIALLY-labeled, non-leaky rows, this returns
a BLOCKED result naming the exact missing data — it never fabricates P&L. When
enough data exists, it aggregates realized paper PnL over settled PAPER_CANDIDATE
fills (executable ask + depth + fees; never midpoint), one trade per window to
avoid overlapping-window leakage.

All outputs are explicitly paper simulation — never reported as real profit.
"""

from __future__ import annotations

from typing import Iterable


def aggregate_paper_pnl(entries: Iterable) -> dict:
    """Aggregate realized paper PnL over settled, filled paper entries (pure).

    Counts at most one settled fill per slug (overlapping-window guard). Returns
    paper-simulation metrics; the caller must label them non-profit.
    """
    seen_slugs: set = set()
    trades: list[dict] = []
    for e in entries:
        d = e if isinstance(e, dict) else e.__dict__
        if d.get("decision") != "PAPER_CANDIDATE":
            continue
        if d.get("fill_status") not in ("filled", "partial"):
            continue
        if d.get("realized_pnl") is None or d.get("known_outcome") is None:
            continue
        slug = d.get("slug")
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        trades.append(d)

    n = len(trades)
    if n == 0:
        return {"paper_simulation": True, "n_trades": 0, "note": "no settled paper fills"}
    pnls = [t["realized_pnl"] for t in trades]
    fees = sum(t.get("fees") or 0.0 for t in trades)
    wins = sum(1 for p in pnls if p > 0)
    return {
        "paper_simulation": True,            # NOT real profit
        "n_trades": n,
        "net_pnl_paper": sum(pnls),
        "avg_pnl_paper": sum(pnls) / n,
        "hit_rate": wins / n,
        "fees_paid": fees,
        "best": max(pnls),
        "worst": min(pnls),
        "note": "paper simulation over settled fills (executable ask+depth+fees, no midpoint)",
    }


def run_paper_backtest(config, *, asset: str = "BTC", duration: str = "5m") -> dict:
    """Gated backtest. Blocked (with exact missing data) until enough rows."""
    from ..paper.pipeline import run_paper_decisions
    from ..paper.readiness import load_readiness

    readiness = load_readiness(config, asset=asset, duration=duration)
    if not readiness["backtest_allowed"]:
        return {
            "status": "blocked",
            "reason": "insufficient usable OFFICIALLY-labeled rows for a backtest",
            "needed_usable_labeled_rows": readiness["min_backtest_rows"],
            "have_usable_labeled_rows": readiness["usable_labeled_rows"],
            "missing_fields": readiness["missing_fields"],
            "readiness": readiness,
        }
    entries, _ = run_paper_decisions(config, asset=asset, duration=duration)
    result = aggregate_paper_pnl(entries)
    result["status"] = "ran"
    result["readiness"] = readiness
    return result
