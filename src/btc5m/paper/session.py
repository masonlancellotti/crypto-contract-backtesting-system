"""Session summary writer — reports/paper/session_summary-YYYYMMDD.md.

Renders a human-readable record-only/paper session report: data volumes,
decisions by state, fills/rejections, blockers, safety status, and next actions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import AppConfig


def _fmt_dict(d: dict) -> str:
    if not d:
        return "  (none)"
    return "\n".join(f"  - {k}: {v}" for k, v in d.items())


def render_session_summary(session: dict, *, ref_ms: Optional[int] = None) -> str:
    ts = ref_ms if ref_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    when = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    data = session.get("data", {})
    decisions = session.get("decisions_by_state", {})
    readiness = session.get("readiness", {})
    safety = session.get("safety", {})
    blockers = session.get("blockers", [])
    next3 = session.get("next_actions", [])

    lines = [
        f"# btc5m paper session summary — {when}",
        "",
        "> Record-only / paper. No live orders placed. Fills use executable",
        "> ask/bid + depth (never midpoint). Numbers are paper simulation, not profit.",
        "",
        "## Data captured / used",
        f"- markets seen: {data.get('markets_seen', 0)}",
        f"- Polymarket book snapshots: {data.get('book_snapshots', 0)}",
        f"- underlying events (coinbase+binance): {data.get('underlying_events', 0)}",
        f"- settlement-line records: {data.get('line_records', 0)}",
        f"- label rows: {data.get('label_rows', 0)}",
        f"- feature rows: {data.get('feature_rows', 0)}",
        "",
        "## Decisions by state",
        _fmt_dict(decisions),
        "",
        "## Paper trading",
        f"- paper candidates: {session.get('paper_candidates', 0)}",
        f"- simulated fills: {session.get('fills', 0)}",
        f"- rejections / not-traded: {session.get('rejections', 0)}",
        f"- ledger entries written: {session.get('ledger_entries', 0)}",
        f"- ledger file: {session.get('ledger_file', 'n/a')}",
        "",
        "## Data readiness (training/backtest gating)",
        f"- completed windows: {readiness.get('completed_windows', 0)}",
        f"- official labels: {readiness.get('official_labels', 0)}",
        f"- provisional labels: {readiness.get('provisional_labels', 0)}",
        f"- MANUAL_REVIEW: {readiness.get('manual_review', 0)}",
        f"- usable labeled rows: {readiness.get('usable_labeled_rows', 0)}",
        f"- training_allowed: {readiness.get('training_allowed', False)}",
        f"- backtest_allowed: {readiness.get('backtest_allowed', False)}",
        "",
        "## Main blockers",
        ("\n".join(f"- {b}" for b in blockers) if blockers else "- (none reported)"),
        "",
        "## Safety status",
        f"- trading_mode: {safety.get('trading_mode')}",
        f"- live_trading_enabled: {safety.get('live_trading_enabled')}",
        f"- kill_switch_enabled: {safety.get('kill_switch_enabled')}",
        f"- live_permitted: {safety.get('live_permitted')}",
        f"- notifier: {safety.get('notifier')}",
        f"- chainlink_official_configured: {safety.get('chainlink_configured')}",
        "",
        "## Next 3 actions",
        ("\n".join(f"{i+1}. {a}" for i, a in enumerate(next3[:3])) if next3 else "1. (none)"),
        "",
    ]
    return "\n".join(lines)


def write_session_summary(config: AppConfig, session: dict, *, ref_ms: Optional[int] = None) -> Path:
    reports_dir = config.reports_path() / "paper"
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = ref_ms if ref_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    day = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y%m%d")
    path = reports_dir / f"session_summary-{day}.md"
    path.write_text(render_session_summary(session, ref_ms=ref_ms), encoding="utf-8")
    return path
