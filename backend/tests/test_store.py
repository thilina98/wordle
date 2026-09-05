"""Contract tests for game persistence."""

from wordle.game import GameState
from wordle.store import InMemoryGameStore


def a_game(target="crane"):
    return GameState(target=target)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestInMemoryGameStore:
    def test_create_returns_an_opaque_id_and_stores_the_game(self):
        store = InMemoryGameStore()
        game = a_game()
        game_id = store.create(game)
        assert isinstance(game_id, str) and game_id
        assert store.get(game_id) is game

    def test_ids_are_unique(self):
        store = InMemoryGameStore()
        ids = {store.create(a_game()) for _ in range(50)}
        assert len(ids) == 50

    def test_unknown_id_returns_none(self):
        assert InMemoryGameStore().get("nope") is None

    def test_delete_removes_the_game(self):
        store = InMemoryGameStore()
        game_id = store.create(a_game())
        store.delete(game_id)
        assert store.get(game_id) is None

    def test_delete_is_idempotent(self):
        InMemoryGameStore().delete("nope")  # must not raise

    def test_game_expires_after_its_ttl(self):
        clock = FakeClock()
        store = InMemoryGameStore(ttl_seconds=60, clock=clock)
        game_id = store.create(a_game())
        clock.advance(61)
        assert store.get(game_id) is None

    def test_access_extends_the_ttl(self):
        # A game in active play must not be dropped mid-guess.
        clock = FakeClock()
        store = InMemoryGameStore(ttl_seconds=60, clock=clock)
        game_id = store.create(a_game())
        clock.advance(50)
        assert store.get(game_id) is not None
        clock.advance(50)
        assert store.get(game_id) is not None

    def test_expired_games_are_purged_not_just_hidden(self):
        clock = FakeClock()
        store = InMemoryGameStore(ttl_seconds=60, clock=clock)
        store.create(a_game())
        clock.advance(61)
        store.create(a_game())
        assert len(store) == 1

    def test_capacity_evicts_the_least_recently_used(self):
        store = InMemoryGameStore(max_games=2)
        first = store.create(a_game())
        second = store.create(a_game())
        store.get(first)  # first is now the most recently used
        third = store.create(a_game())
        assert store.get(second) is None
        assert store.get(first) is not None
        assert store.get(third) is not None

    def test_never_exceeds_capacity(self):
        store = InMemoryGameStore(max_games=5)
        for _ in range(20):
            store.create(a_game())
        assert len(store) == 5
