"""Label dataset construction with purge/embargo for overlapping windows.

Overlapping 5-minute windows share information, so train/validation splits MUST
purge training samples whose label horizon overlaps the validation window and
embargo a buffer afterward (López de Prado). ``purge_embargo_indices`` is
implemented and tested; full dataset joining remains a scaffold.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class LabeledSample:
    """A point-in-time sample whose label resolves over [as_of_ms, label_end_ms]."""

    as_of_ms: int       # when features were observed (no look-ahead past this)
    label_end_ms: int   # when the label is known (e.g. contract expiry)


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Inclusive interval overlap test."""
    return a_start <= b_end and b_start <= a_end


def purge_embargo_indices(
    samples: Sequence[LabeledSample],
    test_start_ms: int,
    test_end_ms: int,
    *,
    embargo_ms: int = 0,
) -> list[int]:
    """Return indices of samples SAFE to train on given a test window.

    A sample is dropped if its label horizon ``[as_of_ms, label_end_ms]``
    overlaps the test window ``[test_start_ms, test_end_ms]`` (purge) or falls
    within the embargo region just after the test window
    ``(test_end_ms, test_end_ms + embargo_ms]`` (embargo).

    Samples fully before the test window (and outside the embargo) or fully
    after it are kept.
    """
    if test_end_ms < test_start_ms:
        raise ValueError("test_end_ms must be >= test_start_ms")
    if embargo_ms < 0:
        raise ValueError("embargo_ms must be >= 0")

    embargo_end = test_end_ms + embargo_ms
    safe: list[int] = []
    for i, s in enumerate(samples):
        if s.label_end_ms < s.as_of_ms:
            raise ValueError(f"sample {i}: label_end_ms before as_of_ms")
        # Purge: label horizon overlaps the test window.
        if _overlaps(s.as_of_ms, s.label_end_ms, test_start_ms, test_end_ms):
            continue
        # Embargo: sample begins within the embargo region after the test window.
        if test_end_ms < s.as_of_ms <= embargo_end:
            continue
        safe.append(i)
    return safe


def build_labeled_dataset(*args: Any, **kwargs: Any) -> Any:
    """Join features with settlement labels into a training table. Scaffold."""
    raise NotImplementedError("build_labeled_dataset is a scaffold.")


def purge_embargo_split(*args: Any, **kwargs: Any) -> Any:
    """Produce leakage-safe train/val indices via purge + embargo. Scaffold.

    Use :func:`purge_embargo_indices` for the core single-window logic.
    """
    raise NotImplementedError("purge_embargo_split is a scaffold (see purge_embargo_indices).")
