"""Append-only trial registry — the honest cumulative multiple-testing budget.

If you re-mine the same data every week, the *true* number of trials behind any
"significant" discovery is the cumulative count across ALL runs, not just the latest one.
Forgetting this is the most common way quants fool themselves over time. The registry logs
every run (data fingerprint, search-space id, trial count, candidates + gauntlet verdicts)
to an append-only JSONL, and `cumulative_trials()` sums the budget for a given data x space
so the Deflated Sharpe Ratio can be deflated by the real N."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional


class TrialRegistry:
    def __init__(self, path: str):
        self.path = path

    def log_run(self, *, data_fingerprint: str, space_id: str, n_trials: int,
                candidates: Optional[list] = None, meta: Optional[dict] = None) -> dict:
        rec = {
            "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"),
            "ts": datetime.now(timezone.utc).isoformat(),
            "data_fingerprint": data_fingerprint,
            "space_id": space_id,
            "n_trials": int(n_trials),
            "candidates": candidates or [],
            "meta": meta or {},
        }
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        return rec

    def runs(self) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        out = []
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return out

    def cumulative_trials(self, *, space_id: str, data_fingerprint: Optional[str] = None) -> int:
        """Total trials ever run for this search space (optionally restricted to a data
        fingerprint). Use this as DSR's n_trials to deflate honestly across re-mining."""
        total = 0
        for r in self.runs():
            if r.get("space_id") != space_id:
                continue
            if data_fingerprint is not None and r.get("data_fingerprint") != data_fingerprint:
                continue
            total += int(r.get("n_trials", 0))
        return total
