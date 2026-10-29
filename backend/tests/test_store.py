"""Contract tests for game persistence.

Every test runs against both stores, so the two cannot drift apart. Tests
specific to durability live in TestSqliteDurability at the bottom.
"""

import pytest

from wordle.game import Difficulty, GameState
from wordle.store import InMemoryGameStore, SqliteGameStore

VOCABULARY = frozenset({"crane", "state", "tasty"})


def a_game(target="crane"):
    return GameState(target=target, vocabulary=VOCABULARY)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(params=["memory", "sqlite"])
def make_store(request, tmp_path):
    """Build either store with the same arguments."""
    created = []

    def build(**kwargs):
        if request.param == "memory":
            if "clock" in kwargs:
                # One clock for both, so the two stores report the same times.
                kwargs.setdefault("wall_clock", kwargs["clock"])
            store = InMemoryGameStore(**kwargs)
        else:
            kwargs.setdefault("clock", None)
            clock = kwargs.pop("clock")
            store = SqliteGameStore(
                tmp_path / f"games{len(created)}.db",
                vocabulary_for=lambda length: VOCABULARY,
                **({"clock": clock} if clock else {}),
                **kwargs,
            )
        created.append(store)
        return store

    yield build
    for store in created:
        close = getattr(store, "close", None)
        if close:
            close()


class TestGameStoreContract:
    def test_create_returns_an_opaque_id_and_stores_the_game(self, make_store):
        store = make_store()
        game_id = store.create(a_game())
        assert isinstance(game_id, str) and game_id
        assert store.get(game_id).target == "crane"

    def test_ids_are_unique(self, make_store):
        store = make_store()
        assert len({store.create(a_game()) for _ in range(50)}) == 50

    def test_unknown_id_returns_none(self, make_store):
        assert make_store().get("nope") is None

    def test_delete_removes_the_game(self, make_store):
        store = make_store()
        game_id = store.create(a_game())
        store.delete(game_id)
        assert store.get(game_id) is None

    def test_delete_is_idempotent(self, make_store):
        make_store().delete("nope")  # must not raise

    def test_an_unowned_game_is_visible_to_everyone(self, make_store):
        store = make_store()
        game_id = store.create(a_game())
        assert store.get(game_id) is not None
        assert store.get(game_id, viewer="player-1") is not None

    def test_an_owned_game_is_visible_to_its_owner_only(self, make_store):
        store = make_store()
        game_id = store.create(a_game(), owner="player-1")
        assert store.get(game_id, viewer="player-1") is not None
        assert store.get(game_id, viewer="player-2") is None
        assert store.get(game_id) is None

    def test_ownership_survives_a_save(self, make_store):
        store = make_store()
        game = a_game()
        game_id = store.create(game, owner="player-1")
        game.guess("crane")
        store.save(game_id, game)
        assert store.get(game_id) is None
        assert store.get(game_id, viewer="player-1") is not None

    def test_delete_owned_by_removes_only_that_players_games(self, make_store):
        store = make_store()
        mine = [store.create(a_game(), owner="player-1") for _ in range(2)]
        theirs = store.create(a_game(), owner="player-2")
        anonymous = store.create(a_game())
        assert store.delete_owned_by("player-1") == 2
        assert all(store.get(g, viewer="player-1") is None for g in mine)
        assert store.get(theirs, viewer="player-2") is not None
        assert store.get(anonymous) is not None

    def test_delete_owned_by_with_no_games_is_harmless(self, make_store):
        assert make_store().delete_owned_by("nobody") == 0

    def test_saved_guesses_are_read_back(self, make_store):
        store = make_store()
        game = a_game()
        game_id = store.create(game)
        game.guess("state")
        store.save(game_id, game)

        reloaded = store.get(game_id)
        assert [a.guess for a in reloaded.attempts] == ["state"]
        assert reloaded.attempts_remaining == 4

    def test_save_of_an_unknown_id_is_harmless(self, make_store):
        make_store().save("nope", a_game())  # must not raise

    def test_game_expires_after_its_ttl(self, make_store):
        clock = FakeClock()
        store = make_store(ttl_seconds=60, clock=clock)
        game_id = store.create(a_game())
        clock.advance(61)
        assert store.get(game_id) is None

    def test_access_extends_the_ttl(self, make_store):
        # A game in active play must not be dropped mid-guess.
        clock = FakeClock()
        store = make_store(ttl_seconds=60, clock=clock)
        game_id = store.create(a_game())
        clock.advance(50)
        assert store.get(game_id) is not None
        clock.advance(50)
        assert store.get(game_id) is not None

    def test_expired_games_are_purged_not_just_hidden(self, make_store):
        clock = FakeClock()
        store = make_store(ttl_seconds=60, clock=clock)
        store.create(a_game())
        clock.advance(61)
        store.create(a_game())
        assert len(store) == 1

    def test_capacity_evicts_the_least_recently_used(self, make_store):
        clock = FakeClock()
        store = make_store(max_games=2, clock=clock)
        first = store.create(a_game())
        clock.advance(1)
        second = store.create(a_game())
        clock.advance(1)
        store.get(first)  # first is now the most recently used
        clock.advance(1)
        third = store.create(a_game())
        assert store.get(second) is None
        assert store.get(first) is not None
        assert store.get(third) is not None

    def test_never_exceeds_capacity(self, make_store):
        clock = FakeClock()
        store = make_store(max_games=5, clock=clock)
        for _ in range(20):
            clock.advance(1)
            store.create(a_game())
        assert len(store) == 5


def played(game: GameState, *guesses: str, at: float = 0.0) -> GameState:
    """Make guesses one second apart, starting at `at`."""
    for i, word in enumerate(guesses):
        game.guess(word, now=at + i)
    return game


class TestResultsWaitingToBeRecorded:
    """Owned games that are over wait in the store until statistics take them."""

    OWNER = "player-1"

    def test_an_owned_game_saved_finished_waits_to_be_recorded(self, make_store):
        store = make_store()
        game_id = store.create(a_game(), owner=self.OWNER)
        game = played(store.get(game_id, viewer=self.OWNER), "state", "crane", at=500.0)
        store.save(game_id, game)
        [pending] = store.pending_results()
        assert (pending.game_id, pending.owner, pending.abandoned) == (game_id, self.OWNER, False)
        assert pending.ended_at == 501.0
        assert pending.game.is_won

    def test_unowned_and_unfinished_games_have_nothing_to_record(self, make_store):
        store = make_store()
        anonymous = store.create(a_game())
        store.save(anonymous, played(store.get(anonymous), "crane"))
        unfinished = store.create(a_game(), owner=self.OWNER)
        store.save(unfinished, played(store.get(unfinished, viewer=self.OWNER), "state"))
        assert store.pending_results() == []

    def test_a_recorded_game_stays_visible_and_stops_waiting(self, make_store):
        store = make_store()
        game_id = store.create(a_game(), owner=self.OWNER)
        store.save(game_id, played(store.get(game_id, viewer=self.OWNER), "crane"))
        store.mark_recorded(game_id)
        assert store.pending_results() == []
        assert store.get(game_id, viewer=self.OWNER).is_won
        # Saving it again does not queue it again.
        store.save(game_id, store.get(game_id, viewer=self.OWNER))
        assert store.pending_results() == []

    def test_waiting_results_come_out_earliest_ended_first(self, make_store):
        store = make_store()
        late = store.create(a_game(), owner=self.OWNER)
        early = store.create(a_game(), owner=self.OWNER)
        store.save(late, played(store.get(late, viewer=self.OWNER), "crane", at=900.0))
        store.save(early, played(store.get(early, viewer=self.OWNER), "crane", at=100.0))
        assert [p.game_id for p in store.pending_results()] == [early, late]

    def test_a_new_game_abandons_the_open_one_in_the_same_combination(self, make_store):
        store = make_store()
        open_id = store.create(a_game(), owner=self.OWNER)
        store.save(open_id, played(store.get(open_id, viewer=self.OWNER), "state", "tasty"))
        assert store.abandon_open_games(self.OWNER, 5, Difficulty.NORMAL) == 1
        [pending] = store.pending_results()
        assert (pending.game_id, pending.abandoned) == (open_id, True)
        # An abandoned game cannot be played on.
        assert store.get(open_id, viewer=self.OWNER) is None

    def test_one_guess_is_not_enough_to_abandon(self, make_store):
        store = make_store()
        game_id = store.create(a_game(), owner=self.OWNER)
        store.save(game_id, played(store.get(game_id, viewer=self.OWNER), "state"))
        assert store.abandon_open_games(self.OWNER, 5, Difficulty.NORMAL) == 0
        assert store.get(game_id, viewer=self.OWNER) is not None

    def test_other_combinations_and_players_are_left_alone(self, make_store):
        store = make_store()
        hard = store.create(GameState("crane", VOCABULARY, max_attempts=4), owner=self.OWNER)
        theirs = store.create(a_game(), owner="player-2")
        for game_id, owner in ((hard, self.OWNER), (theirs, "player-2")):
            store.save(game_id, played(store.get(game_id, viewer=owner), "state", "tasty"))
        assert store.abandon_open_games(self.OWNER, 5, Difficulty.NORMAL) == 0
        assert store.abandon_open_games(self.OWNER, 6, Difficulty.HARD) == 0
        assert store.abandon_open_games(self.OWNER, 5, Difficulty.HARD) == 1

    def test_a_recorded_abandoned_game_is_gone(self, make_store):
        store = make_store()
        game_id = store.create(a_game(), owner=self.OWNER)
        store.save(game_id, played(store.get(game_id, viewer=self.OWNER), "state", "tasty"))
        store.abandon_open_games(self.OWNER, 5, Difficulty.NORMAL)
        store.mark_recorded(game_id)
        assert len(store) == 0

    def test_expiring_abandons_a_game_with_two_guesses(self, make_store):
        clock = FakeClock()
        store = make_store(ttl_seconds=60, clock=clock)
        game_id = store.create(a_game(), owner=self.OWNER)
        store.save(game_id, played(store.get(game_id, viewer=self.OWNER), "state", "tasty"))
        last_touched = clock.now
        clock.advance(61)
        store.create(a_game())  # purges
        [pending] = store.pending_results()
        assert (pending.game_id, pending.abandoned) == (game_id, True)
        assert pending.ended_at == last_touched

    def test_expiring_drops_a_game_with_one_guess(self, make_store):
        clock = FakeClock()
        store = make_store(ttl_seconds=60, clock=clock)
        game_id = store.create(a_game(), owner=self.OWNER)
        store.save(game_id, played(store.get(game_id, viewer=self.OWNER), "state"))
        clock.advance(61)
        store.create(a_game())
        assert store.pending_results() == []
        assert len(store) == 1

    def test_a_waiting_result_outlives_its_ttl_and_the_capacity(self, make_store):
        clock = FakeClock()
        store = make_store(ttl_seconds=60, max_games=1, clock=clock)
        game_id = store.create(a_game(), owner=self.OWNER)
        store.save(game_id, played(store.get(game_id, viewer=self.OWNER), "crane"))
        clock.advance(61)
        store.create(a_game())
        assert [p.game_id for p in store.pending_results()] == [game_id]

    def test_deleting_a_player_drops_their_waiting_results(self, make_store):
        store = make_store()
        game_id = store.create(a_game(), owner=self.OWNER)
        store.save(game_id, played(store.get(game_id, viewer=self.OWNER), "crane"))
        store.delete_owned_by(self.OWNER)
        assert store.pending_results() == []


class TestSqliteDurability:
    """The point of the sqlite store: a destroyed container loses nothing."""

    def _store(self, path, **kwargs):
        return SqliteGameStore(path, vocabulary_for=lambda length: VOCABULARY, **kwargs)

    def test_a_database_from_before_accounts_opens_and_its_games_are_unowned(self, tmp_path):
        import sqlite3

        path = tmp_path / "old.db"
        with sqlite3.connect(path) as conn:
            conn.execute(
                "CREATE TABLE games (id TEXT PRIMARY KEY, target TEXT NOT NULL,"
                " max_attempts INTEGER NOT NULL, attempts TEXT NOT NULL,"
                " touched_at REAL NOT NULL)"
            )
            conn.execute("INSERT INTO games VALUES ('old', 'crane', 5, '[]', 9e12)")
        conn.close()
        store = self._store(path, clock=lambda: 9e12)
        try:
            assert store.get("old", viewer="anyone") is not None
            assert store.create(a_game(), owner="player-1")
        finally:
            store.close()

    def test_a_game_survives_the_process_that_made_it(self, tmp_path):
        path = tmp_path / "games.db"
        store = self._store(path)
        game = a_game()
        game_id = store.create(game)
        game.guess("state")
        store.save(game_id, game)
        store.close()

        # A new store over the same file is what a restarted container sees.
        revived = self._store(path)
        try:
            reloaded = revived.get(game_id)
            assert reloaded is not None
            assert reloaded.target == "crane"
            assert [a.guess for a in reloaded.attempts] == ["state"]
            assert reloaded.attempts_remaining == 4
        finally:
            revived.close()

    def test_colours_survive_the_round_trip(self, tmp_path):
        path = tmp_path / "games.db"
        store = self._store(path)
        game = a_game()
        game_id = store.create(game)
        game.guess("state")
        expected = game.attempts[0].colours
        store.save(game_id, game)
        store.close()

        revived = self._store(path)
        try:
            assert revived.get(game_id).attempts[0].colours == expected
        finally:
            revived.close()

    def test_a_finished_game_stays_finished(self, tmp_path):
        path = tmp_path / "games.db"
        store = self._store(path)
        game = a_game()
        game_id = store.create(game)
        game.guess("crane")
        store.save(game_id, game)
        store.close()

        revived = self._store(path)
        try:
            assert revived.get(game_id).is_won
        finally:
            revived.close()

    def test_creates_its_directory(self, tmp_path):
        store = self._store(tmp_path / "nested" / "deeper" / "games.db")
        try:
            assert store.create(a_game())
        finally:
            store.close()

    def test_close_is_safe_to_call_twice(self, tmp_path):
        store = self._store(tmp_path / "games.db")
        store.close()
        store.close()


class TestStaleVocabulary:
    """A stored game can outlive the word list it was written against."""

    def test_sqlite_drops_a_game_whose_target_left_the_vocabulary(self, tmp_path):
        path = tmp_path / "games.db"
        store = SqliteGameStore(path, vocabulary_for=lambda length: VOCABULARY)
        game_id = store.create(a_game("crane"))
        store.close()

        # Same rows, a word list that no longer contains the target.
        reopened = SqliteGameStore(
            path, vocabulary_for=lambda length: frozenset({"state", "tasty"})
        )
        try:
            assert reopened.get(game_id) is None
            assert len(reopened) == 0
        finally:
            reopened.close()
