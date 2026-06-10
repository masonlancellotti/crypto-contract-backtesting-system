"""Contract-level features derived from the Polymarket book + metadata.

Captures executable spread, depth, quote age, and seconds-to-expiry — the
quantities that determine whether any apparent edge is real and tradable.
"""

from __future__ import annotations

from ..schemas import ContractMeta, OrderBook
from ..timeutils import age_ms, now_ms


def contract_features(book: OrderBook, meta: ContractMeta, *, ref_ms: int | None = None) -> dict:
    """Return a flat dict of contract microstructure features.

    Includes quote age and seconds-to-expiry so downstream gates can reject
    stale quotes and near-expiry/edge-of-window contracts.
    """
    ref = ref_ms if ref_ms is not None else now_ms()
    feats: dict[str, float | bool | None] = {
        "best_bid": book.best_bid.price if book.best_bid else None,
        "best_ask": book.best_ask.price if book.best_ask else None,
        "spread": book.spread,
        "mid_diagnostic": book.mid,  # diagnostic only; never a fill assumption
        "is_crossed": book.is_crossed,
        "bid_depth_top": book.best_bid.size if book.best_bid else 0.0,
        "ask_depth_top": book.best_ask.size if book.best_ask else 0.0,
        "quote_age_ms": age_ms(book.ts_ms, ref_ms=ref),
        "seconds_to_expiry": (meta.expiry_ms - ref) / 1000.0 if meta.expiry_ms else None,
        "has_settlement_metadata": meta.has_settlement_metadata,
    }
    return feats
