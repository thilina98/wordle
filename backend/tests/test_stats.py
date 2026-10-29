"""Player statistics, tested through the PlayerStats interface: results in, summaries out.

The contract runs against every adapter. PostgreSQL joins in when
WORDLE_TEST_DATABASE_URL points at a database the tests may wipe.
"""

from __future__ import annotations

import itertools
import os
import threading
import uuid
from dataclasses import replace

import pytest

from tests.conftest import RULES, SCORING_SETTINGS
from wordle.game import Difficulty, GameState, difficulty_of
from wordle.stats import (
    FixedScoringRules,
    GameResult,
    InMemoryPlayerStats,
    NotRecordable,
    Outcome,
)
from wordle.stats.model import as_points

TEST_DATABASE_URL = os.environ.get("WORDLE_TEST_DATABASE_URL")

EASY, NORMAL, HARD = Difficulty.EASY, Difficulty.NORMAL, Difficulty.HARD


class Backend:
    """One adapter under test, and a way to make players it will accept."""

    def __init__(self, stats, new_player, database=None, rules=None):
        self.stats = stats
        self.new_player = new_player
        self.database = database
        self.rules = rules


@pytest.fixture(params=["memory", "postgres"])
def backend(request):
    if request.param == "memory":
        yield Backend(InMemoryPlayerStats(FixedScoringRules(RULES)), lambda: str(uuid.uuid4()))
        return
    if not TEST_DATABASE_URL:
        pytest.skip("WORDLE_TEST_DATABASE_URL not set")
    from tests.postgres import fresh_database
    from wordle.stats.postgres import PostgresPlayerStats, PostgresScoringRules

    database = fresh_database(TEST_DATABASE_URL)
    database.run_data_script("0001_seed_scoring_version_1")

    def new_player() -> str:
        with database.pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO players (display_name) VALUES ('Player') RETURNING player_id"
            ).fetchone()
        return str(row[0])

    rules = PostgresScoringRules(database)
    yield Backend(PostgresPlayerStats(database, rules), new_player, database, rules)
    database.close()


@pytest.fixture
def stats(backend):
    return backend.stats


@pytest.fixture
def player(backend):
    return backend.new_player()


_ids = itertools.count()
_clock = itertools.count(1_000_000, 1_000)


def result(
    player_id: str,
    *,
    won_on: int | None = None,
    abandoned: bool = False,
    length: int = 5,
    attempts: int | None = None,
    seconds: float = 60.0,
) -> GameResult:
    """A game as statistics see it. Each one ends after the one before."""
    attempts = attempts if attempts is not None else length
    if won_on is not None:
        outcome, guesses = Outcome.WON, won_on
    elif abandoned:
        outcome, guesses = Outcome.ABANDONED, 2
    else:
        outcome, guesses = Outcome.LOST, attempts
    ended = float(next(_clock))
    return GameResult(
        game_id=f"game-{next(_ids)}",
        player_id=player_id,
        answer="a" * length,
        word_length=length,
        max_attempts=attempts,
        difficulty=difficulty_of(length, attempts),
        guesses=tuple("b" * length for _ in range(guesses)),
        outcome=outcome,
        attempt_won_on=won_on,
        started_at=ended - seconds,
        ended_at=ended,
    )


def points(r: GameResult) -> float:
    return float(as_points(r.score(RULES)))


class TestCounting:
    def test_a_player_with_no_games_has_an_empty_summary(self, stats, player):
        summary = stats.summary(player)
        assert (summary.games, summary.wins, summary.losses) == (0, 0, 0)
        assert summary.win_percentage is None
        assert summary.average_score is None
        assert summary.highest_score is None
        assert summary.fastest_win_ms is None
        assert summary.guess_distribution == {}

    def test_an_id_that_was_never_a_player_has_an_empty_summary(self, stats):
        assert stats.summary("not-a-uuid").games == 0

    def test_games_wins_losses_and_win_percentage(self, stats, player):
        for r in (
            result(player, won_on=3),
            result(player, won_on=4),
            result(player),
            result(player, abandoned=True),
        ):
            stats.record(r)
        summary = stats.summary(player)
        assert (summary.games, summary.wins, summary.losses) == (4, 2, 2)
        assert summary.win_percentage == 50.0

    def test_recording_the_same_game_twice_counts_it_once(self, stats, player):
        r = result(player, won_on=3)
        stats.record(r)
        stats.record(r)
        assert stats.summary(player).games == 1

    def test_first_and_last_attempt_wins(self, stats, player):
        for r in (
            result(player, won_on=1),
            result(player, won_on=5),  # 5 of 5 allowed
            result(player, won_on=6, attempts=6),  # 6 of 6 allowed
            result(player, won_on=3),
        ):
            stats.record(r)
        summary = stats.summary(player)
        assert summary.first_attempt_wins == 1
        assert summary.last_attempt_wins == 2

    def test_guess_distribution_counts_wins_by_attempt(self, stats, player):
        for r in (
            result(player, won_on=1),
            result(player, won_on=3),
            result(player, won_on=3),
            result(player),
        ):
            stats.record(r)
        assert stats.summary(player).guess_distribution == {1: 1, 3: 2}

    def test_players_do_not_see_each_others_games(self, backend, stats, player):
        other = backend.new_player()
        stats.record(result(other, won_on=3))
        assert stats.summary(player).games == 0


class TestScores:
    def test_total_and_highest_score(self, stats, player):
        games = [result(player, won_on=2), result(player, won_on=4), result(player)]
        for r in games:
            stats.record(r)
        summary = stats.summary(player)
        assert summary.total_score == pytest.approx(sum(points(r) for r in games))
        assert summary.highest_score == points(games[0])

    def test_the_average_skips_losses_and_attempt_one_wins(self, stats, player):
        scored = [result(player, won_on=2), result(player, won_on=4)]
        for r in (
            *scored,
            result(player),
            result(player, abandoned=True),
            result(player, won_on=1),
        ):
            stats.record(r)
        expected = round(sum(points(r) for r in scored) / 2, 2)
        assert stats.summary(player).average_score == expected

    def test_only_losses_have_no_average(self, stats, player):
        stats.record(result(player))
        stats.record(result(player, won_on=1))
        assert stats.summary(player).average_score is None


class TestTimes:
    def test_fastest_and_average_win_time(self, stats, player):
        for r in (
            result(player, won_on=3, seconds=40),
            result(player, won_on=4, seconds=80),
            result(player, seconds=5),  # a loss: never a win time
        ):
            stats.record(r)
        summary = stats.summary(player)
        assert summary.fastest_win_ms == 40_000
        assert summary.average_win_ms == 60_000

    def test_attempt_one_wins_never_count_for_time(self, stats, player):
        stats.record(result(player, won_on=1, seconds=2))
        stats.record(result(player, won_on=3, seconds=50))
        summary = stats.summary(player)
        assert summary.fastest_win_ms == 50_000
        assert summary.average_win_ms == 50_000


class TestStreaks:
    def test_streaks_need_both_a_length_and_a_difficulty(self, stats, player):
        stats.record(result(player, won_on=3))
        assert stats.summary(player).current_streak is None
        assert stats.summary(player, word_length=5).best_streak is None
        assert stats.summary(player, difficulty=NORMAL).current_streak is None
        assert stats.summary(player, word_length=5, difficulty=NORMAL).current_streak == 1

    def test_wins_in_a_row_and_a_loss_resets(self, stats, player):
        for r in (
            result(player, won_on=3),
            result(player, won_on=1),  # attempt-1 wins count for streaks
            result(player, won_on=4),
            result(player),
            result(player, won_on=2),
        ):
            stats.record(r)
        summary = stats.summary(player, word_length=5, difficulty=NORMAL)
        assert (summary.current_streak, summary.best_streak) == (1, 3)

    def test_abandoning_resets_the_streak(self, stats, player):
        stats.record(result(player, won_on=3))
        stats.record(result(player, abandoned=True))
        assert stats.summary(player, word_length=5, difficulty=NORMAL).current_streak == 0

    def test_a_loss_in_another_combination_does_not_break_it(self, stats, player):
        stats.record(result(player, won_on=3))
        stats.record(result(player, attempts=4))  # hard: a loss
        stats.record(result(player, length=6))  # another mode: a loss
        stats.record(result(player, won_on=2))
        summary = stats.summary(player, word_length=5, difficulty=NORMAL)
        assert (summary.current_streak, summary.best_streak) == (2, 2)

    def test_a_combination_never_played_has_a_zero_streak(self, stats, player):
        summary = stats.summary(player, word_length=7, difficulty=HARD)
        assert (summary.current_streak, summary.best_streak) == (0, 0)


class TestFilters:
    @pytest.fixture
    def played(self, stats, player):
        """Five letters at every difficulty, and six letters at normal."""
        for r in (
            result(player, won_on=3),  # 5 normal
            result(player, attempts=6, won_on=6),  # 5 easy
            result(player, attempts=4),  # 5 hard, lost
            result(player, length=6, won_on=4),  # 6 normal
            result(player, length=6),  # 6 normal, lost
        ):
            stats.record(r)
        return player

    def test_no_filter_is_every_game(self, stats, played):
        assert stats.summary(played).games == 5

    def test_a_mode_covers_every_difficulty_at_that_length(self, stats, played):
        summary = stats.summary(played, word_length=5)
        assert (summary.games, summary.wins) == (3, 2)

    def test_a_difficulty_covers_every_length(self, stats, played):
        summary = stats.summary(played, difficulty=NORMAL)
        assert (summary.games, summary.wins) == (3, 2)
        assert summary.guess_distribution == {3: 1, 4: 1}

    def test_both_narrow_to_one_combination(self, stats, played):
        summary = stats.summary(played, word_length=6, difficulty=NORMAL)
        assert (summary.games, summary.wins, summary.current_streak) == (2, 1, 0)

    def test_a_filter_nothing_matches_is_empty(self, stats, played):
        assert stats.summary(played, word_length=6, difficulty=HARD).games == 0


class TestConcurrency:
    def test_games_finishing_at_once_are_all_counted(self, stats, player):
        games = [result(player, won_on=3) for _ in range(20)]
        threads = [threading.Thread(target=stats.record, args=(r,)) for r in games]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        summary = stats.summary(player, word_length=5, difficulty=NORMAL)
        assert (summary.games, summary.wins, summary.best_streak) == (20, 20, 20)


class TestGameResult:
    """A GameState becomes a result only once there is something to record."""

    VOCABULARY = frozenset({"crane", "state", "tasty"})

    def _game(self, **kwargs) -> GameState:
        return GameState(target="crane", vocabulary=self.VOCABULARY, **kwargs)

    def test_a_win(self):
        game = self._game()
        game.guess("state", now=100.0)
        game.guess("crane", now=130.0)
        r = GameResult.of("g", "p", game, ended_at=130.0, abandoned=False)
        assert (r.outcome, r.attempt_won_on, r.duration_ms) == (Outcome.WON, 2, 30_000)
        assert r.difficulty is NORMAL
        assert r.guesses == ("state", "crane")

    def test_a_loss(self):
        game = self._game(max_attempts=2)
        game.guess("state", now=0.0)
        game.guess("tasty", now=10.0)
        r = GameResult.of("g", "p", game, ended_at=10.0, abandoned=False)
        assert (r.outcome, r.attempt_won_on, r.difficulty) == (Outcome.LOST, None, HARD)

    def test_a_game_still_being_played_is_not_recordable(self):
        game = self._game()
        game.guess("state", now=0.0)
        with pytest.raises(NotRecordable):
            GameResult.of("g", "p", game, ended_at=1.0, abandoned=False)

    def test_abandoned_after_one_guess_is_not_recordable(self):
        game = self._game()
        game.guess("state", now=0.0)
        with pytest.raises(NotRecordable):
            GameResult.of("g", "p", game, ended_at=1.0, abandoned=True)

    def test_abandoned_after_two_guesses_is_an_abandoned_loss(self):
        game = self._game()
        game.guess("state", now=0.0)
        game.guess("tasty", now=5.0)
        r = GameResult.of("g", "p", game, ended_at=50.0, abandoned=True)
        assert (r.outcome, r.won, r.score(RULES).score) == (Outcome.ABANDONED, False, 0.0)

    def test_an_untimed_game_is_not_recordable(self):
        game = self._game()
        game.guess("crane")
        with pytest.raises(NotRecordable):
            GameResult.of("g", "p", game, ended_at=1.0, abandoned=False)

    def test_the_end_is_never_before_the_start(self):
        game = self._game()
        game.guess("state", now=100.0)
        game.guess("tasty", now=110.0)
        r = GameResult.of("g", "p", game, ended_at=50.0, abandoned=True)
        assert r.ended_at == r.started_at == 100.0


# --- PostgreSQL only ------------------------------------------------------


@pytest.fixture
def postgres(backend):
    if backend.database is None:
        pytest.skip("PostgreSQL only")
    return backend


def _add_version(database, version: int, *, max_base: float, active: bool) -> None:
    with database.pool.connection() as conn, conn.transaction():
        if active:
            conn.execute("UPDATE scoring_versions SET is_active = false")
        conn.execute(
            "INSERT INTO scoring_versions (scoring_version, is_active, max_base,"
            " last_attempt_ratio, time_bonus_cap, seconds_per_letter, difficulty_step,"
            " normal_max_score, score_precision) VALUES (%s, %s, %s, 0.2, 0.2, 60, 1.25, 10, 2)",
            (version, active, max_base),
        )


class TestPostgres:
    def test_a_result_for_a_deleted_player_is_dropped(self, postgres):
        postgres.stats.record(result(str(uuid.uuid4()), won_on=3))  # no such player: no error

    def test_deleting_a_player_deletes_their_statistics(self, postgres, player):
        postgres.stats.record(result(player, won_on=3))
        with postgres.database.pool.connection() as conn:
            conn.execute("DELETE FROM players WHERE player_id = %s", (player,))
            left = conn.execute(
                "SELECT (SELECT count(*) FROM game_results) + (SELECT count(*) FROM game_scores)"
                " + (SELECT count(*) FROM player_stats)"
            ).fetchone()[0]
        assert left == 0

    def test_a_game_records_the_version_it_was_played_under(self, postgres, player):
        postgres.stats.record(result(player, won_on=3))
        with postgres.database.pool.connection() as conn:
            row = conn.execute(
                "SELECT scoring_version_played_under, difficulty, outcome FROM game_results"
            ).fetchone()
        assert row == (1, "normal", "won")

    def test_recording_picks_up_a_newly_active_version(self, postgres, player):
        stats, rules = postgres.stats, postgres.rules
        stats.record(result(player, won_on=2))
        _add_version(postgres.database, 2, max_base=50, active=True)
        assert rules.current().version == 1  # cached until something reads the database

        r = result(player, won_on=2)
        stats.record(r)
        assert rules.current().version == 2
        # Only the active version's figures are read: the game under version 1 is not.
        summary = stats.summary(player)
        assert summary.games == 1
        v2 = replace(RULES, max_base=50.0, version=2)
        assert summary.total_score == float(as_points(r.score(v2)))

    def test_the_cache_refreshes_on_its_timer(self, postgres):
        from wordle.stats.postgres import PostgresScoringRules

        now = [0.0]
        rules = PostgresScoringRules(postgres.database, refresh_seconds=10, clock=lambda: now[0])
        _add_version(postgres.database, 2, max_base=50, active=True)
        assert rules.current().version == 1
        now[0] = 11.0
        assert rules.current().version == 2

    def test_no_active_version_stops_startup(self, postgres):
        from wordle.stats.postgres import NoActiveScoringVersion, PostgresScoringRules

        with postgres.database.pool.connection() as conn:
            conn.execute("UPDATE scoring_versions SET is_active = false")
        with pytest.raises(NoActiveScoringVersion, match="0001_seed_scoring_version_1"):
            PostgresScoringRules(postgres.database)

    def test_only_one_version_can_be_active(self, postgres):
        import psycopg

        _add_version(postgres.database, 2, max_base=50, active=False)
        with pytest.raises(psycopg.errors.UniqueViolation):
            with postgres.database.pool.connection() as conn:
                conn.execute("UPDATE scoring_versions SET is_active = true")

    def test_the_seed_matches_the_settings_constants(self, postgres):
        """The seeded version 1 and the documented WORDLE_SCORING_* values agree."""
        assert _fields(postgres.rules.current()) == _fields(RULES)
        assert RULES.max_base == SCORING_SETTINGS["scoring_max_base"]


def _fields(rules) -> dict:
    return {name: getattr(rules, name) for name in rules.__slots__}


class TestDataScripts:
    def test_a_script_runs_once(self, postgres):
        from wordle.db import DataScriptError

        assert "0001_seed_scoring_version_1" in postgres.database.data_scripts_run()
        with pytest.raises(DataScriptError, match="already been run"):
            postgres.database.run_data_script("0001_seed_scoring_version_1")

    def test_an_unknown_script_is_refused(self, postgres):
        from wordle.db import DataScriptError

        with pytest.raises(DataScriptError, match="No data script"):
            postgres.database.run_data_script("9999_nothing")


class TestThroughTheApi:
    """Accounts, games and statistics on one real database, end to end."""

    def test_a_signed_in_game_reaches_the_statistics(self, postgres, settings):
        from fastapi.testclient import TestClient

        from tests.fakes import FakeIdentityProvider
        from wordle.accounts import Accounts
        from wordle.accounts.postgres import PostgresPlayerRepository
        from wordle.app import create_app

        provider = FakeIdentityProvider()
        app = create_app(
            settings,
            accounts=Accounts(provider, PostgresPlayerRepository(postgres.database)),
            stats=postgres.stats,
            scoring_rules=postgres.rules,
        )
        try:
            app.state.catalogue.answers(5).random_word = lambda rng=None: "crane"
            player = TestClient(app)
            player.headers["Authorization"] = f"Bearer {provider.person('google|1')}"
            game_id = player.post("/api/games").json()["game_id"]
            player.post(f"/api/games/{game_id}/guesses", json={"guess": "state"})
            board = player.post(f"/api/games/{game_id}/guesses", json={"guess": "crane"}).json()

            stats = player.get(
                "/api/players/me/stats", params={"word_length": 5, "difficulty": "normal"}
            ).json()
            assert (stats["games"], stats["wins"], stats["current_streak"]) == (1, 1, 1)
            assert stats["total_score"] == board["score"]["score"]

            # Deleting the player takes their statistics with them.
            assert player.delete("/api/players/me").status_code == 204
            with postgres.database.pool.connection() as conn:
                assert conn.execute("SELECT count(*) FROM game_results").fetchone()[0] == 0
        finally:
            app.state.store.close()
