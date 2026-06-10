"""Persistent paper ledger — append-only JSONL under data/paper/.

Each entry records the decision, the EXECUTABLE price used (ask/bid, never
midpoint), costs, net edge, reason codes, line/label source status, the
simulated fill (price/size/status), and the known official outcome + realized
PnL once settled. This is the audit trail for paper trading.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import AppConfig

LEDGER_STREAM = "paper_ledger"


@dataclass
class LedgerEntry:
    timestamp_ms: int
    slug: Optional[str]
    condition_id: Optional[str]
    side: Optional[str]                 # BUY_YES | BUY_NO | None
    decision: str                       # NO_ACTION | WATCH | MANUAL_REVIEW | PAPER_CANDIDATE
    model_yes_probability: Optional[float]
    executable_price: Optional[float]   # the ask used to enter (NOT midpoint)
    estimated_costs: Optional[float]
    net_edge: Optional[float]
    reason_codes: list = field(default_factory=list)
    line_source_status: str = "UNKNOWN"
    label_source_status: str = "UNKNOWN"
    fill_status: str = "not_traded"     # filled | partial | rejected | not_traded
    sim_price: Optional[float] = None   # realized avg fill price
    sim_size: Optional[float] = None
    fees: Optional[float] = None
    known_outcome: Optional[int] = None  # official_outcome if settled, else None
    realized_pnl: Optional[float] = None
    is_paper: bool = True               # always True; never a live order


class PaperLedger:
    def __init__(self, config: AppConfig):
        self.config = config
        self.dir: Path = config.data_path() / "paper"

    def _day_file(self, ref_ms: Optional[int] = None) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        ts = ref_ms if ref_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
        day = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y%m%d")
        return self.dir / f"{LEDGER_STREAM}-{day}.jsonl"

    def write(self, entries, *, ref_ms: Optional[int] = None) -> int:
        path = self._day_file(ref_ms)
        n = 0
        with path.open("a", encoding="utf-8") as fh:
            for e in entries:
                rec = asdict(e) if isinstance(e, LedgerEntry) else e
                fh.write(json.dumps(rec) + "\n")
                n += 1
        return n


def load_ledger(paper_dir: Path) -> list[dict]:
    """Load all ledger entries from data/paper/paper_ledger-*.jsonl."""
    out: list[dict] = []
    for path in sorted(Path(paper_dir).glob(f"{LEDGER_STREAM}-*.jsonl")):
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            out.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except OSError:
            continue
    return out
