from btc5m.data.book_builder import BookBuilder
from btc5m.schemas import Outcome


def test_snapshot_sorts_and_validates():
    bb = BookBuilder()
    book = bb.apply_snapshot(
        "C1",
        Outcome.YES,
        bids=[(0.54, 100), (0.55, 200)],   # intentionally unsorted
        asks=[(0.58, 300), (0.57, 150)],
        ts_ms=1_000,
        recv_ms=1_005,
    )
    assert book.best_bid.price == 0.55
    assert book.best_ask.price == 0.57
    assert not book.is_crossed
    assert BookBuilder.is_valid(book)
    assert bb.get("C1", Outcome.YES) is book


def test_crossed_book_detected():
    bb = BookBuilder()
    book = bb.apply_snapshot("C2", Outcome.YES, bids=[(0.60, 10)], asks=[(0.59, 10)])
    assert book.is_crossed
    assert not BookBuilder.is_valid(book)


def test_zero_size_levels_dropped():
    bb = BookBuilder()
    book = bb.apply_snapshot("C3", Outcome.NO, bids=[(0.5, 0)], asks=[(0.6, 5)])
    assert book.best_bid is None
    assert book.best_ask.price == 0.6
