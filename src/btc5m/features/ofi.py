"""Order-flow imbalance (OFI) features.

OFI from best-level book changes is a standard short-horizon drift signal.
The top-level helper is implemented (stdlib) for unit-testing; multi-level and
trade-signed variants are scaffolds.
"""

from __future__ import annotations


def best_level_ofi(
    prev_bid: tuple[float, float],
    prev_ask: tuple[float, float],
    bid: tuple[float, float],
    ask: tuple[float, float],
) -> float:
    """Cont/Kukanov/Stoikov best-level OFI between two snapshots.

    Each argument is (price, size). Returns a signed flow value: positive ==
    net buy pressure.
    """
    pb_p, pb_s = prev_bid
    pa_p, pa_s = prev_ask
    b_p, b_s = bid
    a_p, a_s = ask

    if b_p > pb_p:
        d_bid = b_s
    elif b_p == pb_p:
        d_bid = b_s - pb_s
    else:
        d_bid = -pb_s

    if a_p < pa_p:
        d_ask = a_s
    elif a_p == pa_p:
        d_ask = a_s - pa_s
    else:
        d_ask = -pa_s

    return d_bid - d_ask


def multilevel_ofi(prev_levels: list, levels: list) -> float:
    """OFI aggregated across multiple book levels. Scaffold."""
    raise NotImplementedError("multilevel_ofi is a scaffold.")
