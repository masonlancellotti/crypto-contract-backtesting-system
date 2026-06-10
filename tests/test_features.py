from btc5m.features.duration import duration_features
from btc5m.features.microprice import microprice
from btc5m.features.ofi import best_level_ofi
from btc5m.features.queue_imbalance import top_imbalance
from btc5m.schemas import BookLevel, OrderBook, Outcome


def _book(bid_sz=100, ask_sz=100):
    return OrderBook(
        contract_id="C",
        outcome=Outcome.YES,
        bids=[BookLevel(0.55, bid_sz)],
        asks=[BookLevel(0.57, ask_sz)],
    )


def test_top_imbalance_sign():
    assert top_imbalance(_book(200, 100)) > 0
    assert top_imbalance(_book(100, 200)) < 0
    assert top_imbalance(_book(100, 100)) == 0


def test_microprice_within_spread_and_not_midpoint_when_skewed():
    book = _book(300, 100)  # more bid size -> microprice pulled toward ask side weight
    mp = microprice(book)
    assert 0.55 <= mp <= 0.57
    assert mp != book.mid  # skewed book => not the midpoint


def test_duration_features_bounds():
    f = duration_features(150, window=300)
    assert f["frac_remaining"] == 0.5
    assert not f["is_expired"]
    f2 = duration_features(-5, window=300)
    assert f2["is_expired"]
    assert f2["frac_remaining"] == 0.0


def test_best_level_ofi_buy_pressure():
    # ask lifted (price up, same/declining size) and bid grows -> positive OFI
    val = best_level_ofi(
        prev_bid=(0.55, 100), prev_ask=(0.57, 100), bid=(0.56, 150), ask=(0.58, 100)
    )
    assert val > 0
