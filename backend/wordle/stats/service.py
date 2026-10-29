"""The statistics seams, and their in-memory adapters.

The PostgreSQL adapters live in `postgres.py` so that importing this package
never needs a database driver.
"""

from __future__ import annotations

import threading
from typing import Protocol

from ..game import Difficulty
from ..scoring import ScoringRules
from .model import ComboStats, GameResult, StatsSummary, as_points, summarise


class StatsUnavailable(Exception):
    """The statistics store could not be reached. Maps to 503.

    Never loses a result: an unrecorded game waits in the game store and is
    tried again.
    """


class ScoringRulesSource(Protocol):
    """Where the scoring constants come from."""

    def current(self) -> ScoringRules:
        """The rules new scores are worked out with. Cheap: called per request."""
        ...


class PlayerStats(Protocol):
    """Every finished game of a signed-in player, and the statistics drawn from them.

    Both methods raise StatsUnavailable when the store cannot be reached.
    """

    def record(self, result: GameResult) -> None:
        """Store one result, scored under the active scoring version.

        Idempotent by game id: recording the same game again changes nothing,
        so a retry is always safe. Results must arrive in the order the games
        ended, because that is the order streaks count in. A result for a
        player who no longer exists is dropped.
        """
        ...

    def summary(
        self,
        player_id: str,
        *,
        word_length: int | None = None,
        difficulty: Difficulty | None = None,
    ) -> StatsSummary:
        """Statistics over the player's games matching the filter. None matches all.

        Streaks come back only when both word length and difficulty are given.
        An unknown player has an empty summary, not an error.
        """
        ...


class FixedScoringRules:
    """Rules that never change: from settings, or set by a test."""

    def __init__(self, rules: ScoringRules) -> None:
        self._rules = rules

    def current(self) -> ScoringRules:
        return self._rules


class InMemoryPlayerStats:
    """Process-local statistics. For tests, and for running without a database."""

    def __init__(self, rules: ScoringRulesSource) -> None:
        self._rules = rules
        self._lock = threading.Lock()
        self._results: dict[str, GameResult] = {}
        self._rows: dict[tuple[str, int, Difficulty], ComboStats] = {}

    def record(self, result: GameResult) -> None:
        points = as_points(result.score(self._rules.current()))
        with self._lock:
            if result.game_id in self._results:
                return
            self._results[result.game_id] = result
            key = (result.player_id, result.word_length, result.difficulty)
            row = self._rows.get(key) or ComboStats(result.word_length, result.difficulty)
            self._rows[key] = row.after(result, points)

    def summary(
        self,
        player_id: str,
        *,
        word_length: int | None = None,
        difficulty: Difficulty | None = None,
    ) -> StatsSummary:
        def wanted(length: int, label: Difficulty) -> bool:
            return (word_length is None or length == word_length) and (
                difficulty is None or label == difficulty
            )

        with self._lock:
            rows = [
                row
                for (owner, length, label), row in self._rows.items()
                if owner == player_id and wanted(length, label)
            ]
            distribution: dict[int, int] = {}
            for r in self._results.values():
                if r.player_id == player_id and r.won and wanted(r.word_length, r.difficulty):
                    distribution[r.attempt_won_on] = distribution.get(r.attempt_won_on, 0) + 1
        return summarise(
            rows,
            distribution,
            one_combination=word_length is not None and difficulty is not None,
        )
