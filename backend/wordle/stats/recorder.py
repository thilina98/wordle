"""Moves results from the game store into statistics.

The game store holds every owned game that is over (or abandoned) and not yet
recorded. `flush` writes them out, earliest ended first, and tells the store
which made it. One path for everything: a game just finished, one abandoned,
and one left over from an outage all go the same way.
"""

from __future__ import annotations

import logging
import threading

from ..store import GameStore
from .model import GameResult, NotRecordable
from .service import PlayerStats, StatsUnavailable

log = logging.getLogger("wordle.stats")

#: How often the server retries results an outage held back, in seconds.
RETRY_SECONDS = 60


class ResultRecorder:
    def __init__(self, store: GameStore, stats: PlayerStats) -> None:
        self._store = store
        self._stats = stats
        # One flush at a time, so results are recorded in the order they ended.
        self._lock = threading.Lock()

    def flush(self, batch: int = 100) -> int:
        """Record what is waiting. Returns how many were recorded.

        Stops at the first outage and leaves the rest waiting: recording a
        later game before an earlier one would count streaks out of order.
        Never raises for an outage.
        """
        recorded = 0
        with self._lock:
            while True:
                pending = self._store.pending_results(batch)
                for item in pending:
                    try:
                        result = GameResult.of(
                            item.game_id,
                            item.owner,
                            item.game,
                            ended_at=item.ended_at,
                            abandoned=item.abandoned,
                        )
                    except NotRecordable as exc:
                        log.warning("Not recording game %s: %s", item.game_id, exc)
                        self._store.mark_recorded(item.game_id)
                        continue
                    try:
                        self._stats.record(result)
                    except StatsUnavailable:
                        log.warning("Statistics unavailable; %d result(s) wait", len(pending))
                        return recorded
                    self._store.mark_recorded(item.game_id)
                    recorded += 1
                if len(pending) < batch:
                    return recorded
