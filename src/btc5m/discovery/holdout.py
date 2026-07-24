"""Sealed holdout vault — the data the search is NEVER allowed to see until final validation.

The single most important guard against self-deception: carve a hash-pinned holdout before
any mining, and validate the few gauntlet survivors on it exactly ONCE. The holdout is a
forward block (the gold-standard test of generalization to the future) plus a seeded random
embargoed block (tests non-recency generalization). The search set excludes both, with an
embargo buffer so no label horizon leaks across the seam.

The manifest stores a fingerprint of the underlying windows; `verify()` refuses to proceed
if the data has shifted under it, so you can never silently validate on changed data."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone


def fingerprint(windows: list[dict]) -> str:
    """Stable SHA-256 of the window set: (ticker, close_ms, label) sorted by close."""
    items = sorted(((w["ticker"], int(w["close_ms"]), int(w["label"])) for w in windows),
                   key=lambda t: (t[1], t[0]))
    h = hashlib.sha256()
    for tk, cm, lab in items:
        h.update(f"{tk}|{cm}|{lab}\n".encode())
    return h.hexdigest()


@dataclass
class HoldoutVault:
    created_at: str
    fingerprint: str
    params: dict
    search_keys: list          # window tickers usable by the search
    holdout_keys: list         # SEALED — only for final validation
    counts: dict = field(default_factory=dict)

    # ---- construction ---------------------------------------------------- #
    @classmethod
    def build(cls, windows: list[dict], *, holdout_fraction: float = 0.25,
              forward_share: float = 0.6, embargo: int = 2, seed: int = 7) -> "HoldoutVault":
        wins = sorted(windows, key=lambda w: (int(w["close_ms"]), w["ticker"]))
        n = len(wins)
        if n < 20:
            raise ValueError(f"need >= 20 windows to build a vault; have {n}")
        n_hold = max(4, int(round(n * holdout_fraction)))
        n_fwd = max(1, int(round(n_hold * forward_share)))
        n_rand = max(0, n_hold - n_fwd)

        fwd_idx = set(range(n - n_fwd, n))                 # most-recent forward block
        # random holdout drawn as a few CONTIGUOUS blocks spread through the middle
        # (not scattered singletons — those embargo out ~2*embargo neighbours each).
        import random
        rng = random.Random(seed)
        rand_idx: set = set()
        mid_n = n - n_fwd
        if n_rand and mid_n > 0:
            n_blocks = max(1, min(3, n_rand // 5)) or 1
            block_len = max(1, n_rand // n_blocks)
            seg = mid_n / n_blocks
            for b in range(n_blocks):
                seg_lo = int(b * seg)
                seg_hi = max(seg_lo + 1, int((b + 1) * seg) - block_len)
                start = rng.randint(seg_lo, max(seg_lo, min(seg_hi, mid_n - block_len)))
                rand_idx |= set(range(start, min(start + block_len, mid_n)))
        hold_idx = fwd_idx | rand_idx

        # embargo: any window within `embargo` positions of a holdout window is dropped
        # from BOTH sets (it is neither safely search nor cleanly holdout).
        bad = set()
        for h in hold_idx:
            for d in range(-embargo, embargo + 1):
                j = h + d
                if 0 <= j < n and j not in hold_idx:
                    bad.add(j)
        search_idx = [i for i in range(n) if i not in hold_idx and i not in bad]

        search_keys = [wins[i]["ticker"] for i in sorted(search_idx)]
        holdout_keys = [wins[i]["ticker"] for i in sorted(hold_idx)]
        return cls(
            created_at=datetime.now(timezone.utc).isoformat(),
            fingerprint=fingerprint(wins),
            params={"holdout_fraction": holdout_fraction, "forward_share": forward_share,
                    "embargo": embargo, "seed": seed, "n_total": n},
            search_keys=search_keys, holdout_keys=holdout_keys,
            counts={"n_total": n, "n_search": len(search_keys), "n_holdout": len(holdout_keys),
                    "n_forward": len(fwd_idx), "n_random": len(rand_idx),
                    "n_embargoed_out": len(bad)},
        )

    # ---- helpers --------------------------------------------------------- #
    def split_rows(self, rows: list[dict], *, which: str = "search") -> list[dict]:
        """Filter feature rows to the search OR (sealed) holdout window set."""
        keyset = set(self.search_keys if which == "search" else self.holdout_keys)
        return [r for r in rows if (r.get("ticker") or r.get("market_ticker")) in keyset]

    def verify(self, windows: list[dict]) -> bool:
        """True iff the current windows still match the pinned fingerprint."""
        return fingerprint(windows) == self.fingerprint

    def to_dict(self) -> dict:
        return {"created_at": self.created_at, "fingerprint": self.fingerprint,
                "params": self.params, "counts": self.counts,
                "search_keys": self.search_keys, "holdout_keys": self.holdout_keys}

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    @classmethod
    def load(cls, path: str) -> "HoldoutVault":
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return cls(created_at=d["created_at"], fingerprint=d["fingerprint"],
                   params=d["params"], search_keys=d["search_keys"],
                   holdout_keys=d["holdout_keys"], counts=d.get("counts", {}))
