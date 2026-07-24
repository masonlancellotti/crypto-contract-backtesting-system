"""Combinatorial Purged Cross-Validation (CPCV) over distinct 15m windows.

Splits are ALWAYS by distinct, non-overlapping 15m windows (never per-row — rows within
a window are heavily overlapping and leak). Because 15m windows do not overlap, ordering
windows by close time makes index-adjacency == time-adjacency, so purge+embargo reduces to
removing train windows within `embargo` positions of any test window. CPCV evaluates every
C(n_groups, k_test) way of holding out k_test contiguous groups, giving many leakage-safe
train/test paths instead of one.

`make_window_panel` reuses the project's window grouping; the splitters return index arrays
into the close-sorted window list."""
from __future__ import annotations

import itertools
from typing import Iterator

from ..venues.kalshi.splits import group_windows


def make_window_panel(rows: list[dict]) -> list[dict]:
    """Group feature rows into close-sorted, labeled window descriptors (one per window)."""
    wins = group_windows(rows)
    out = []
    for w in wins:
        if w.get("close_ms") is None or w.get("label") is None:
            continue
        out.append({"ticker": w["ticker"], "close_ms": w["close_ms"],
                    "label": int(w["label"]), "rows": w["rows"]})
    return out


def _embargoed(test_idx: set, n: int, embargo: int) -> set:
    """Indices within `embargo` positions of any test index (purge buffer)."""
    bad = set()
    for t in test_idx:
        for d in range(-embargo, embargo + 1):
            j = t + d
            if 0 <= j < n:
                bad.add(j)
    return bad


def combinatorial_purged_splits(n_windows: int, *, n_groups: int = 6, k_test: int = 2,
                                embargo: int = 1) -> Iterator[tuple[list[int], list[int]]]:
    """Yield (train_idx, test_idx) over close-sorted window indices for every choice of
    `k_test` contiguous groups as the test set, with purge+embargo applied to train.

    Number of splits = C(n_groups, k_test)."""
    if n_windows < n_groups or n_groups < 2 or not (1 <= k_test < n_groups):
        return
    bounds = [round(i * n_windows / n_groups) for i in range(n_groups + 1)]
    groups = [list(range(bounds[i], bounds[i + 1])) for i in range(n_groups)]
    for combo in itertools.combinations(range(n_groups), k_test):
        test_idx = sorted(i for g in combo for i in groups[g])
        if not test_idx:
            continue
        bad = _embargoed(set(test_idx), n_windows, embargo)
        test_set = set(test_idx)
        train_idx = [i for i in range(n_windows) if i not in test_set and i not in bad]
        if train_idx and test_idx:
            yield train_idx, test_idx


def n_cpcv_splits(n_groups: int, k_test: int) -> int:
    from math import comb
    return comb(n_groups, k_test) if (n_groups >= 2 and 1 <= k_test < n_groups) else 0


def purged_walk_forward(n_windows: int, *, n_splits: int = 5, embargo: int = 1
                        ) -> Iterator[tuple[list[int], list[int]]]:
    """Expanding-window walk-forward over windows (train = everything before the test fold,
    minus embargo); the chronological complement to CPCV for time-causal evaluation."""
    if n_windows < n_splits + 1:
        return
    edges = [round(k * n_windows / (n_splits + 1)) for k in range(1, n_splits + 2)]
    for i in range(1, len(edges)):
        tr_end = edges[i - 1]
        te_start, te_end = edges[i - 1], edges[i]
        test_idx = list(range(te_start, te_end))
        if not test_idx:
            continue
        bad = _embargoed(set(test_idx), n_windows, embargo)
        train_idx = [j for j in range(tr_end) if j not in bad and j < te_start]
        if train_idx and test_idx:
            yield train_idx, test_idx
