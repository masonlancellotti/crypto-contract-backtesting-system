"""Backtest / calibration report generation (scaffold).

Writes reliability curves, PnL-after-cost summaries, and ablation tables under
REPORTS_DIR. No profitability is claimed without paper/live evidence.
"""

from __future__ import annotations

from typing import Any


def write_backtest_report(*args: Any, **kwargs: Any) -> Any:
    """Render a backtest report to REPORTS_DIR. Scaffold."""
    raise NotImplementedError("write_backtest_report is a scaffold.")
