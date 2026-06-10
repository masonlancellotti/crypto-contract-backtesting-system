"""Purged + embargoed, window-level chronological splits.

Splits are by DISTINCT 15-minute windows (never random rows): rows within a window
are heavily overlapping and would leak across a row-level split. Train/validation
folds are chronological by window close time; an embargo of >=1 full window is
inserted between train and validation so no training label horizon [as_of, close]
can overlap a validation window (15m windows don't overlap, so one embargoed window
guarantees separation). Reports windows/rows/label-balance per split.
"""

from __future__ import annotations

from typing import Optional

WINDOW_MS = 15 * 60 * 1000


def _window_key(row: dict) -> Optional[str]:
    return row.get("ticker") or row.get("market_ticker")


def _close_ms(row: dict):
    return row.get("market_close_ts_ms") or row.get("close_ms")


def group_windows(rows: list[dict]) -> list[dict]:
    """Group rows into windows ordered by close time. Returns window descriptors."""
    by_win: dict[str, dict] = {}
    for r in rows:
        wk = _window_key(r)
        if wk is None:
            continue
        w = by_win.setdefault(wk, {"ticker": wk, "close_ms": _close_ms(r), "rows": [],
                                   "label": r.get("label_yes_resolved")})
        w["rows"].append(r)
        if w["close_ms"] is None:
            w["close_ms"] = _close_ms(r)
    return sorted(by_win.values(), key=lambda w: (w["close_ms"] is None, w["close_ms"] or 0))


def _balance(rows: list[dict]) -> dict:
    yes = sum(1 for r in rows if r.get("label_yes_resolved") == 1)
    no = sum(1 for r in rows if r.get("label_yes_resolved") == 0)
    return {"YES": yes, "NO": no}


def chronological_split(rows: list[dict], *, val_fraction: float = 0.3,
                        embargo_windows: int = 1) -> dict:
    """One chronological train/val split with an embargo gap between them."""
    windows = group_windows(rows)
    n = len(windows)
    result = {
        "n_windows": n, "embargo_windows": embargo_windows,
        "train_windows": 0, "val_windows": 0, "embargoed_windows": 0, "purged_windows": 0,
        "train_rows": 0, "val_rows": 0, "applied": False,
        "train_label_balance": {"YES": 0, "NO": 0}, "val_label_balance": {"YES": 0, "NO": 0},
        "no_leak": True, "reason": None,
    }
    if n < embargo_windows + 2:
        result["reason"] = (f"need >= {embargo_windows + 2} windows for a purged split; have {n}")
        return result

    n_val = max(1, int(round(n * val_fraction)))
    n_val = min(n_val, n - embargo_windows - 1)  # leave >=1 train window + embargo
    val = windows[n - n_val:]
    embargo = windows[n - n_val - embargo_windows: n - n_val] if embargo_windows > 0 else []
    train = windows[: n - n_val - embargo_windows]

    train_rows = [r for w in train for r in w["rows"]]
    val_rows = [r for w in val for r in w["rows"]]
    # Leakage check: latest TRAIN label horizon (close) must end before the
    # earliest VAL window's as_of/close (embargo guarantees the gap).
    no_leak = True
    if train and val:
        last_train_close = max((w["close_ms"] or 0) for w in train)
        first_val_close = min((w["close_ms"] or 0) for w in val)
        no_leak = (first_val_close - last_train_close) >= WINDOW_MS * max(1, embargo_windows)

    result.update(
        applied=True, train_windows=len(train), val_windows=len(val),
        embargoed_windows=len(embargo), purged_windows=len(embargo),
        train_rows=len(train_rows), val_rows=len(val_rows),
        train_label_balance=_balance(train_rows), val_label_balance=_balance(val_rows),
        no_leak=bool(no_leak),
    )
    return result


def walk_forward_splits(rows: list[dict], *, n_splits: int = 3,
                        embargo_windows: int = 1) -> list[dict]:
    """Expanding-window walk-forward folds (chronological, embargoed)."""
    windows = group_windows(rows)
    n = len(windows)
    folds: list[dict] = []
    if n < n_splits + embargo_windows + 1:
        return folds
    val_size = max(1, (n - embargo_windows) // (n_splits + 1))
    for k in range(1, n_splits + 1):
        val_start = k * val_size + embargo_windows
        val_end = val_start + val_size
        if val_end > n:
            break
        train = windows[: k * val_size]
        val = windows[val_start:val_end]
        if not train or not val:
            continue
        tr = [r for w in train for r in w["rows"]]
        vr = [r for w in val for r in w["rows"]]
        folds.append({
            "fold": k, "train_windows": len(train), "val_windows": len(val),
            "embargoed_windows": embargo_windows, "train_rows": len(tr), "val_rows": len(vr),
            "train_label_balance": _balance(tr), "val_label_balance": _balance(vr),
        })
    return folds


def three_way_window_split(rows: list[dict], *, fracs=(0.5, 0.25, 0.25),
                           embargo_windows: int = 1) -> dict:
    """Chronological train / calibration / test split BY WINDOW with embargo gaps.

    Used so the model is fit on TRAIN, the calibrator on CALIB, and metrics on TEST
    — three disjoint, time-ordered window sets (no row-level leakage, embargoed).
    """
    windows = group_windows(rows)
    n = len(windows)
    out = {"applied": False, "reason": None, "n_windows": n,
           "train_idx": [], "calib_idx": [], "test_idx": [],
           "train_windows": 0, "calib_windows": 0, "test_windows": 0,
           "embargo_windows": embargo_windows}
    need = 3 + 2 * embargo_windows
    if n < need:
        out["reason"] = f"need >= {need} windows for a 3-way embargoed split; have {n}"
        return out
    n_train = max(1, int(round(n * fracs[0])))
    n_calib = max(1, int(round(n * fracs[1])))
    # keep >=1 test window after both embargo gaps
    n_calib = min(n_calib, n - n_train - 2 * embargo_windows - 1)
    train = windows[:n_train]
    calib = windows[n_train + embargo_windows: n_train + embargo_windows + n_calib]
    test = windows[n_train + n_calib + 2 * embargo_windows:]
    train_w = {w["ticker"] for w in train}
    calib_w = {w["ticker"] for w in calib}
    test_w = {w["ticker"] for w in test}
    for i, r in enumerate(rows):
        wk = _window_key(r)
        if wk in train_w:
            out["train_idx"].append(i)
        elif wk in calib_w:
            out["calib_idx"].append(i)
        elif wk in test_w:
            out["test_idx"].append(i)
    out.update(applied=bool(test_w and train_w and calib_w),
               train_windows=len(train), calib_windows=len(calib), test_windows=len(test))
    if not out["applied"] and out["reason"] is None:
        out["reason"] = "one of train/calib/test ended up empty"
    return out


def walk_forward_indices(rows: list[dict], *, n_splits: int = 3,
                         embargo_windows: int = 1) -> list[tuple[list[int], list[int]]]:
    """Expanding walk-forward folds as (train_idx, val_idx) row-index pairs."""
    windows = group_windows(rows)
    n = len(windows)
    folds: list[tuple[list[int], list[int]]] = []
    if n < n_splits + embargo_windows + 1:
        return folds
    val_size = max(1, (n - embargo_windows) // (n_splits + 1))
    pos_by_ticker = {}
    for r_i, r in enumerate(rows):
        pos_by_ticker.setdefault(_window_key(r), []).append(r_i)
    for k in range(1, n_splits + 1):
        val_start = k * val_size + embargo_windows
        val_end = val_start + val_size
        if val_end > n:
            break
        train_w = {w["ticker"] for w in windows[: k * val_size]}
        val_w = {w["ticker"] for w in windows[val_start:val_end]}
        tr = [i for tk in train_w for i in pos_by_ticker.get(tk, [])]
        vl = [i for tk in val_w for i in pos_by_ticker.get(tk, [])]
        if tr and vl:
            folds.append((sorted(tr), sorted(vl)))
    return folds


def split_indices(rows: list[dict], *, val_fraction: float = 0.3,
                  embargo_windows: int = 1) -> tuple[list[int], list[int]]:
    """Row indices for (train, val) under the chronological window split."""
    windows = group_windows(rows)
    n = len(windows)
    if n < embargo_windows + 2:
        return list(range(len(rows))), []
    n_val = max(1, int(round(n * val_fraction)))
    n_val = min(n_val, n - embargo_windows - 1)
    val_windows = {w["ticker"] for w in windows[n - n_val:]}
    embargo_set = {w["ticker"] for w in windows[n - n_val - embargo_windows: n - n_val]}
    train_idx, val_idx = [], []
    for i, r in enumerate(rows):
        wk = _window_key(r)
        if wk in val_windows:
            val_idx.append(i)
        elif wk in embargo_set:
            continue  # embargoed/purged
        else:
            train_idx.append(i)
    return train_idx, val_idx
