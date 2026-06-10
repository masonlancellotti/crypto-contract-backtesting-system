"""Typed data schemas for the btc5m system.

Stdlib-only dataclasses so the package imports without third-party deps. These
model the core domain: order books, quotes, contracts, model outputs, trade
candidates, orders, and fills.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .timeutils import now_ms


class Outcome(str, Enum):
    """Binary outcome side of a Polymarket contract."""

    YES = "YES"
    NO = "NO"


class OrderSide(str, Enum):
    """Direction of an order on a given outcome token."""

    BUY = "BUY"
    SELL = "SELL"


class CandidateAction(str, Enum):
    """What to do with an evaluated candidate.

    Uncertain candidates are kept as WATCH / MANUAL_REVIEW, never auto-traded.
    """

    TRADE = "TRADE"
    WATCH = "WATCH"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    REJECT = "REJECT"


class TradingMode(str, Enum):
    OFFLINE = "offline"
    RECORD_ONLY = "record-only"
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


@dataclass(frozen=True)
class BookLevel:
    """A single price level in an order book."""

    price: float  # in probability units [0, 1] for Polymarket binaries
    size: float


@dataclass
class OrderBook:
    """Normalized order book for one outcome token of a contract.

    Bids are descending by price, asks ascending. Prices are in [0, 1].
    """

    contract_id: str
    outcome: Outcome
    bids: list[BookLevel] = field(default_factory=list)
    asks: list[BookLevel] = field(default_factory=list)
    ts_ms: int = field(default_factory=now_ms)  # source/exchange timestamp
    recv_ms: int = field(default_factory=now_ms)  # local receive timestamp

    @property
    def best_bid(self) -> Optional[BookLevel]:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> Optional[BookLevel]:
        return self.asks[0] if self.asks else None

    @property
    def mid(self) -> Optional[float]:
        """Midpoint — for diagnostics ONLY. Never assume fills here."""
        if self.best_bid and self.best_ask:
            return (self.best_bid.price + self.best_ask.price) / 2.0
        return None

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return self.best_ask.price - self.best_bid.price
        return None

    @property
    def is_crossed(self) -> bool:
        """True if the book is crossed/invalid (bid >= ask)."""
        if self.best_bid and self.best_ask:
            return self.best_bid.price >= self.best_ask.price
        return False


@dataclass
class Quote:
    """Reference market quote for the underlying (e.g. Coinbase BTC-USD)."""

    source: str
    symbol: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    ts_ms: int = field(default_factory=now_ms)
    recv_ms: int = field(default_factory=now_ms)

    @property
    def mid(self) -> Optional[float]:
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2.0
        return self.last


class MarketType(str, Enum):
    """How a contract's settlement line is determined.

    UP_DOWN: the line is the underlying price at the window START; resolves
        "Up" (YES) if the END price meets the comparison vs that start price.
        Polymarket BTC 5-minute markets are this type.
    ABOVE_STRIKE: the line is a fixed strike named in the contract.
    UNKNOWN: type not yet determined; do not label.
    """

    UP_DOWN = "up_down"
    ABOVE_STRIKE = "above_strike"
    UNKNOWN = "unknown"


class Comparison(str, Enum):
    """Exact settlement comparison operator. Never guessed."""

    GT = "GT"    # YES if final > line (strict above)
    GTE = "GTE"  # YES if final >= line (at-or-above; ties resolve YES)


@dataclass
class ContractMeta:
    """Settlement-relevant metadata for a 5-minute BTC binary contract.

    The label and execution logic depend on EXACT values here — never infer
    settlement from titles or approximate the expiry. For UP_DOWN markets the
    ``line`` is the window-start reference price and is only known once the
    window opens (``window_start_ms``); until then it is ``None``.
    """

    contract_id: str
    title: str
    asset: str            # e.g. "BTC"
    line: Optional[float]  # the price level the contract resolves against
    expiry_ms: int        # exact expiry timestamp (UTC epoch ms)
    resolution_source: Optional[str] = None  # e.g. which index settles it
    yes_token_id: Optional[str] = None
    no_token_id: Optional[str] = None
    # Polymarket identifiers / discovery metadata
    market_id: Optional[str] = None
    condition_id: Optional[str] = None
    slug: Optional[str] = None
    # Settlement semantics (explicit, never inferred from title text)
    market_type: MarketType = MarketType.UNKNOWN
    comparison: Comparison = Comparison.GT
    yes_outcome_label: str = "YES"   # e.g. "Up"
    no_outcome_label: str = "NO"     # e.g. "Down"
    window_start_ms: Optional[int] = None  # window open (UP_DOWN line is set here)
    status: str = "unknown"          # active | closed | resolved | unknown
    tick_size: Optional[float] = None
    min_order_size: Optional[float] = None
    raw: dict = field(default_factory=dict)

    @property
    def has_settlement_metadata(self) -> bool:
        """Whether we have enough to label/execute safely.

        Requires a concrete numeric line, a positive expiry, and a known asset.
        For UP_DOWN markets this is only true once the start price is recorded.
        """
        return self.line is not None and self.expiry_ms > 0 and self.asset != ""


class LineSourceStatus(str, Enum):
    """Provenance/quality of a captured settlement line.

    OFFICIAL: the exact official settlement/reference price from the resolution
        source (e.g. Chainlink) — settlement-grade truth.
    PROVISIONAL_REFERENCE: a clearly-marked proxy from a BTC feed (Coinbase/
        Binance) captured at/near the window boundary — NOT settlement-grade.
    UNKNOWN: no reliable line value available; do not label as known.
    """

    OFFICIAL = "OFFICIAL"
    PROVISIONAL_REFERENCE = "PROVISIONAL_REFERENCE"
    UNKNOWN = "UNKNOWN"


@dataclass
class SettlementLineRecord:
    """The window-start line for an Up/Down market plus its provenance.

    For Polymarket BTC 5m up/down markets the line is the underlying price at
    ``window_start_ms``. The official Chainlink value is not exposed publicly
    pre-resolution, so feed-derived lines are PROVISIONAL_REFERENCE — never
    silently treated as settlement-grade truth.
    """

    slug: Optional[str]
    condition_id: Optional[str]
    market_id: Optional[str]
    window_start_ms: Optional[int]
    expiry_ms: int
    line_price: Optional[float]
    line_source: str                 # e.g. "coinbase:BTC-USD", "binance:BTCUSDT", "unknown"
    line_source_status: LineSourceStatus
    line_captured_at_ms: Optional[int]
    comparison: "Comparison"
    resolution_source: Optional[str] = None
    detail: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class UnderlyingEvent:
    """A normalized underlying BTC market-data event (spot or futures).

    Carries enough to derive later features (returns, realized vol, spread,
    microprice, queue imbalance, OFI, trade intensity, CVD).
    """

    source: str                  # e.g. "coinbase", "binance_futures"
    symbol: str                  # e.g. "BTC-USD", "BTCUSDT"
    event_type: str              # "trade" | "book" | "ticker"
    exchange_ts_ms: Optional[int]
    recv_ms: int
    price: Optional[float] = None
    size: Optional[float] = None
    side: Optional[str] = None   # aggressor side if inferable: "buy" | "sell"
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None
    spread: Optional[float] = None
    raw_ref: Optional[str] = None  # pointer into raw (e.g. trade id)

    @property
    def mid(self) -> Optional[float]:
        if self.best_bid is not None and self.best_ask is not None:
            return (self.best_bid + self.best_ask) / 2.0
        return self.price


@dataclass
class ModelOutput:
    """Calibrated model estimate for a contract at a point in time."""

    contract_id: str
    p_yes: float                       # calibrated P(YES resolves to 1)
    p_yes_lower: Optional[float] = None  # uncertainty band
    p_yes_upper: Optional[float] = None
    calibration_ts_ms: Optional[int] = None  # when the calibrator was fit
    model_name: str = "baseline"
    ts_ms: int = field(default_factory=now_ms)


@dataclass
class Candidate:
    """A potential trade after edge evaluation (pre-risk, pre-execution)."""

    contract_id: str
    outcome: Outcome
    side: OrderSide
    price: float                 # executable price (NOT midpoint)
    size: float
    model_p: float               # model probability for the traded outcome
    net_edge_cents: float        # post-cost edge in cents (can be negative)
    action: CandidateAction = CandidateAction.WATCH
    reason: str = ""             # why WATCH/REJECT, or notes
    expiry_ms: int = 0
    ts_ms: int = field(default_factory=now_ms)


@dataclass
class Order:
    """An order request handed to an execution adapter."""

    contract_id: str
    outcome: Outcome
    side: OrderSide
    price: float
    size: float
    client_order_id: str = ""
    ts_ms: int = field(default_factory=now_ms)


@dataclass
class Fill:
    """Result of an order (paper or live)."""

    order: Order
    filled_size: float
    avg_price: float             # realized avg fill price (with slippage/fees)
    fees: float = 0.0
    status: str = "filled"       # filled | partial | rejected | simulated
    is_paper: bool = True
    reason: str = ""
    ts_ms: int = field(default_factory=now_ms)


@dataclass
class RiskDecision:
    """Outcome of a risk-manager evaluation."""

    approved: bool
    reasons: list[str] = field(default_factory=list)

    @classmethod
    def ok(cls) -> "RiskDecision":
        return cls(approved=True, reasons=[])

    @classmethod
    def blocked(cls, *reasons: str) -> "RiskDecision":
        return cls(approved=False, reasons=list(reasons))
