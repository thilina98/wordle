"""Contract tests for game persistence.

Every test runs against both stores, so the two cannot drift apart. Tests
specific to durability live in TestSqliteDurability at the bottom.
"""

import pytest

from wordle.game import GameState
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
