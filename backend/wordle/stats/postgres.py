"""PostgreSQL adapters for ScoringRulesSource and PlayerStats.

Knows the statistics tables and nothing else; the pool and the schema belong
to `wordle.db`.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable

import psycopg

from ..db import Database
from ..game import Difficulty
from ..scoring import ScoringRules
from .model import ComboStats, GameResult, StatsSummary, as_points, summarise
from .service import StatsUnavailable

log = logging.getLogger("wordle.stats")

#: How long the cached constants are trusted. Scoring versions change rarely,
#: and every recorded game refreshes the cache anyway; this only bounds how
#: long an anonymous game can be scored under a version just retired.
DEFAULT_REFRESH_SECONDS = 60 * 60 * 4

_ACTIVE_RULES = (
    "SELECT scoring_version, max_base, last_attempt_ratio, time_bonus_cap,"
    " seconds_per_letter, difficulty_step, normal_max_score, score_precision"
    " FROM scoring_versions WHERE is_active"
)


class NoActiveScoringVersion(RuntimeError):
    """The database has no active scoring version, so nothing can be scored."""


def _rules(row: tuple) -> ScoringRules:
    version, *constants = row
    return ScoringRules(*constants, version=version)


def _is_uuid(value: str) -> bool:
    """Player ids are UUIDs here; anything else would be a query error, not a miss."""
    try:
        uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        return False
    return True


class PostgresScoringRules:
    """The active scoring version's constants, cached in memory.

    Loaded on creation: a database with no active version stops the server.
    The cache is refreshed when it is older than `refresh_seconds`, and
    whenever recording a game reads a different active version.
    """

    def __init__(
        self,
        database: Database,
        *,
        refresh_seconds: float = DEFAULT_REFRESH_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._pool = database.pool
        self._refresh_seconds = refresh_seconds
        self._clock = clock
        self._lock = threading.Lock()
        rules = self._load()
        if rules is None:
            raise NoActiveScoringVersion(
                "No active scoring version. Run: python -m wordle.db run-data-script "
                "0001_seed_scoring_version_1"
            )
        self._rules = rules
        self._loaded_at = clock()

    def current(self) -> ScoringRules:
        with self._lock:
            stale = self._clock() - self._loaded_at > self._refresh_seconds
        if stale:
            try:
                rules = self._load()
            except psycopg.Error:
                # Old constants beat no score at all; try again next time.
                log.warning(
                    "Could not refresh the scoring rules; keeping version %s", self._rules.version
                )
                rules = None
            if rules is not None:
                self.offer(rules)
        return self._rules

    def offer(self, rules: ScoringRules) -> None:
        """The active rules, as just read from the database by someone else."""
        with self._lock:
            if rules != self._rules:
                log.info("Scoring version %s is now active", rules.version)
            self._rules = rules
            self._loaded_at = self._clock()

    def _load(self) -> ScoringRules | None:
        with self._pool.connection() as conn:
            row = conn.execute(_ACTIVE_RULES).fetchone()
        return _rules(row) if row else None


class PostgresPlayerStats:
    """Results, scores and summaries in PostgreSQL, through the shared pool."""

    def __init__(self, database: Database, rules: PostgresScoringRules) -> None:
        self._pool = database.pool
        self._rules = rules

    def record(self, result: GameResult) -> None:
        try:
            with self._pool.connection() as conn, conn.transaction():
                self._record(conn, result)
        except psycopg.errors.ForeignKeyViolation:
            # The player was deleted after the game ended. Nothing to keep.
            log.info("Dropped result %s: its player no longer exists", result.game_id)
        except psycopg.Error as exc:
            raise StatsUnavailable("Statistics store unavailable") from exc

    def _record(self, conn: psycopg.Connection, result: GameResult) -> None:
        """Caller holds a transaction."""
        # FOR SHARE: a version switch locks this row FOR UPDATE, so a game
        # recorded mid-switch waits, then scores under the new version.
        row = conn.execute(_ACTIVE_RULES + " FOR SHARE").fetchone()
        if row is None:
            raise StatsUnavailable("No active scoring version")
        rules = _rules(row)
        self._rules.offer(rules)
        points = as_points(result.score(rules))

        inserted = conn.execute(
            "INSERT INTO game_results (game_id, player_id, answer, word_length, max_attempts,"
            " difficulty, guesses, outcome, attempt_won_on, started_at, ended_at,"
            " scoring_version_played_under)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, to_timestamp(%s), to_timestamp(%s), %s)"
            " ON CONFLICT (game_id) DO NOTHING RETURNING game_id",
            (
                result.game_id,
                result.player_id,
                result.answer,
                result.word_length,
                result.max_attempts,
                str(result.difficulty),
                list(result.guesses),
                str(result.outcome),
                result.attempt_won_on,
                result.started_at,
                result.ended_at,
                rules.version,
            ),
        ).fetchone()
        if inserted is None:
            return  # recorded before: a retry, or a double submit

        conn.execute(
            "INSERT INTO game_scores (game_id, score) VALUES (%s, %s)", (result.game_id, points)
        )

        # One game's worth of figures, folded into the row atomically. Postgres
        # locks the row, so two games finishing at once cannot lose an update.
        # ComboStats.after is the same fold, for the in-memory adapter.
        one = ComboStats(result.word_length, result.difficulty).after(result, points)
        conn.execute(
            "INSERT INTO player_stats AS s (player_id, scoring_version, word_length, difficulty,"
            " games, wins, first_attempt_wins, last_attempt_wins, total_score, highest_score,"
            " total_win_ms, fastest_win_ms, current_streak, best_streak, updated_at)"
            " VALUES (%s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())"
            " ON CONFLICT (player_id, scoring_version, word_length, difficulty) DO UPDATE SET"
            " games = s.games + 1,"
            " wins = s.wins + EXCLUDED.wins,"
            " first_attempt_wins = s.first_attempt_wins + EXCLUDED.first_attempt_wins,"
            " last_attempt_wins = s.last_attempt_wins + EXCLUDED.last_attempt_wins,"
            " total_score = s.total_score + EXCLUDED.total_score,"
            " highest_score = GREATEST(s.highest_score, EXCLUDED.highest_score),"
            " total_win_ms = s.total_win_ms + EXCLUDED.total_win_ms,"
            # LEAST ignores NULL, so a game with no win time keeps the old fastest.
            " fastest_win_ms = LEAST(s.fastest_win_ms, EXCLUDED.fastest_win_ms),"
            " current_streak = CASE WHEN EXCLUDED.wins = 1 THEN s.current_streak + 1 ELSE 0 END,"
            " best_streak = GREATEST(s.best_streak,"
            "   CASE WHEN EXCLUDED.wins = 1 THEN s.current_streak + 1 ELSE 0 END),"
            " updated_at = EXCLUDED.updated_at",
            (
                result.player_id,
                rules.version,
                result.word_length,
                str(result.difficulty),
                one.wins,
                one.first_attempt_wins,
                one.last_attempt_wins,
                one.total_score,
                one.highest_score,
                one.total_win_ms,
                one.fastest_win_ms,
                one.current_streak,
                one.best_streak,
            ),
        )

    def summary(
        self,
        player_id: str,
        *,
        word_length: int | None = None,
        difficulty: Difficulty | None = None,
    ) -> StatsSummary:
        one_combination = word_length is not None and difficulty is not None
        if not _is_uuid(player_id):
            return summarise([], {}, one_combination=one_combination)
        label = str(difficulty) if difficulty is not None else None
        filters = (
            " AND (%(length)s::smallint IS NULL OR word_length = %(length)s)"
            " AND (%(label)s::text IS NULL OR difficulty = %(label)s)"
        )
        params = {"player": player_id, "length": word_length, "label": label}
        try:
            with self._pool.connection() as conn:
                rows = conn.execute(
                    "SELECT word_length, difficulty, games, wins, first_attempt_wins,"
                    " last_attempt_wins, total_score, highest_score, total_win_ms,"
                    " fastest_win_ms, current_streak, best_streak"
                    " FROM player_stats WHERE player_id = %(player)s"
                    " AND scoring_version = (SELECT scoring_version FROM scoring_versions"
                    " WHERE is_active)" + filters,
                    params,
                ).fetchall()
                distribution = conn.execute(
                    "SELECT attempt_won_on, count(*) FROM game_results"
                    " WHERE player_id = %(player)s AND outcome = 'won'"
                    + filters
                    + " GROUP BY attempt_won_on",
                    params,
                ).fetchall()
        except psycopg.Error as exc:
            raise StatsUnavailable("Statistics store unavailable") from exc
        combos = [
            ComboStats(length, Difficulty(label), *figures) for length, label, *figures in rows
        ]
        return summarise(
            combos,
            {attempt: count for attempt, count in distribution},
            one_combination=one_combination,
        )
