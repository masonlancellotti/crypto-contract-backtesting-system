"""High-resolution, READ-ONLY measurement layer for Kalshi KXBTC15M repricing-lag v2.

Collects Coinbase/Binance public WebSocket ticks + fast Kalshi active-book REST polls at
sub-second / near-sub-second resolution, stamping a local ``recv_ms`` immediately on receipt,
through a threaded, bounded, priority-aware writer (rotation + gzip compression + retention)
so long unattended sessions stay reliable and storage-safe. Optional joined snapshots feed a
later reprice-lag v2 study.

MEASUREMENT ONLY: no orders, no paper, no live, no promotion, no policy. ``live_submission_allowed``
is stamped False on every row and ``HIRES_NO_ORDERS`` is force-true.
"""

from .sources import (  # noqa: F401
    HiResConfig, BaseSource, BinanceWSSource, build_sources,
    coinbase_ticker_event, binance_book_ticker_event, binance_trade_event,
)
from .writer import HiResWriter, PriorityDropQueue, stream_priority, JOINED_STREAM  # noqa: F401
from .compaction import run_hires_compact  # noqa: F401
from .kalshi_ws import (  # noqa: F401
    KalshiWSBookSource, KalshiBook, run_ws_feasibility, ws_book_available,
    auth_headers, subscribe_message, normalize_ws_book, READ_ONLY_BANNER,
)
from .collector import (  # noqa: F401
    HiResCollector, run_hires_record, run_hires_record_loop, run_hires_smoke, run_hires_status,
    reprice_lag_v2_readiness, hires_inputs_available,
)
