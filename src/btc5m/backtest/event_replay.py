"""Event replay engine (scaffold).

Replays recorded raw/normalized JSONL events in timestamp order to reconstruct
point-in-time state for backtesting, preserving original latency where possible.
"""

from __future__ import annotations

from typing import Any, Iterator


class EventReplay:
    def __init__(self, config: Any):
        self.config = config

    def replay(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        """Yield recorded events in time order. Scaffold."""
        raise NotImplementedError("EventReplay.replay is a scaffold.")
