"""Game persistence.

Two adapters behind the GameStore protocol: SQLite on a mounted volume, which
is the default, and an in-memory store for tests and throwaway runs. Anything
that needs a game goes through the protocol, so a third (Redis, say) drops in
without touching the API layer.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .game import Attempt, Colour, GameState

DEFAULT_TTL_SECONDS = 60 * 60 * 4
DEFAULT_MAX_GAMES = 10_000


class GameStore(Protocol):
    """Storage for games in progress.

    A game may have an owner: the player who started it while signed in. An
    owned game is visible to its owner only. An unowned game, started
    anonymously, is visible to anyone holding its id, as every game was before
    accounts existed.
    """

    def create(self, game: GameState, owner: str | None = None) -> str:
        """Store a game and return its id. `owner` is a player id, or None."""
        ...

    def get(self, game_id: str, viewer: str | None = None) -> GameState | None:
        """Fetch a live game that `viewer` may see.

        None if the game is unknown, expired, or owned by someone other than
        `viewer`. The three look the same on purpose: a game id must not
        reveal whether someone else's game exists.
        """
        ...

    def save(self, game_id: str, game: GameState) -> None:
        """Persist changes to a game already in the store."""
        ...

    def delete(self, game_id: str) -> None:
        """Remove a game. Does nothing if it is already gone."""
        ...


def _visible(owner: str | None, viewer: str | None) -> bool:
    """Anyone may see an unowned game; only its owner may see an owned one."""
    return owner is None or owner == viewer


@dataclass(slots=True)
class _Entry:
    game: GameState
    touched_at: float
    owner: str | None = None


class InMemoryGameStore:
    """Process-local store with a sliding TTL and an LRU capacity bound.

    Both limits exist so abandoned games cannot grow without limit. Single
    process only: with more than one worker, a game is only visible to the
    worker that created it.

    Locked, because the routes are sync `def` and FastAPI runs those in a
    thread pool: two requests really do reach the dict at once.
    """

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_games: int = DEFAULT_MAX_GAMES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_games = max_games
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, _Entry] = OrderedDict()

    def create(self, game: GameState, owner: str | None = None) -> str:
        game_id = secrets.token_urlsafe(16)
        with self._lock:
            self._purge_expired()
            self._entries[game_id] = _Entry(game=game, touched_at=self._clock(), owner=owner)
            # Drop the least recently used until we are back within capacity.
            while len(self._entries) > self._max_games:
                self._entries.popitem(last=False)
        return game_id

    def get(self, game_id: str, viewer: str | None = None) -> GameState | None:
        with self._lock:
            entry = self._entries.get(game_id)
            if entry is None or not _visible(entry.owner, viewer):
                return None
            now = self._clock()
            if now - entry.touched_at > self._ttl:
                del self._entries[game_id]
                return None
            entry.touched_at = now
            self._entries.move_to_end(game_id)
            return entry.game

    def save(self, game_id: str, game: GameState) -> None:
        """No-op: `get` handed out the live object, so it is already current."""

    def delete(self, game_id: str) -> None:
        with self._lock:
            self._entries.pop(game_id, None)

    def _purge_expired(self) -> None:
        """Caller holds the lock."""
        cutoff = self._clock() - self._ttl
        expired = [gid for gid, e in self._entries.items() if e.touched_at < cutoff]
        for game_id in expired:
            del self._entries[game_id]

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


class SqliteGameStore:
    """Games on disk, so they outlive the process that created them.

    Point this at a mounted volume and a container can be destroyed and
    rebuilt without anyone losing the board they were part way through.

    Unlike the in-memory store this one keeps copies, not references, so a
    mutated game has to be handed back with `save`.

    `vocabulary_for` maps a word length to the guesses legal at that length. A
    row records its target, so the length to look up is the target's own: games
    of different lengths share one table without the schema knowing.
    """

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS games (
            id           TEXT PRIMARY KEY,
            target       TEXT    NOT NULL,
            max_attempts INTEGER NOT NULL,
            attempts     TEXT    NOT NULL,
            touched_at   REAL    NOT NULL,
            started_at   REAL,
            finished_at  REAL,
            owner_id     TEXT
        );
        CREATE INDEX IF NOT EXISTS games_touched_at ON games (touched_at);
    """

    #: Columns added after the table shipped. A database written by an older
    #: build has the table already, so CREATE TABLE IF NOT EXISTS skips it and
    #: these have to be put on by hand. Games in flight keep playing; they just
    #: score as untimed.
    #: owner_id arrived with accounts; a game from before it is unowned.
    _ADDED_COLUMNS = (("started_at", "REAL"), ("finished_at", "REAL"), ("owner_id", "TEXT"))

    def __init__(
        self,
        path: Path,
        vocabulary_for: Callable[[int], Collection[str]],
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_games: int = DEFAULT_MAX_GAMES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = Path(path)
        self._vocabulary_for = vocabulary_for
        self._ttl = ttl_seconds
        self._max_games = max_games
        # Wall clock, not monotonic: a monotonic value means nothing after a
        # restart, and this table outlives restarts.
        self._clock = clock
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # One connection, guarded by the lock. `sqlite3.connect` as a context
        # manager commits a transaction but does not close the connection, so
        # opening one per call leaks file descriptors.
        self._conn = sqlite3.connect(
            self._path, timeout=5.0, isolation_level=None, check_same_thread=False
        )
        # WAL survives an unclean stop and lets a reader run beside a writer.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(self._SCHEMA)
        self._add_missing_columns()

    def _add_missing_columns(self) -> None:
        existing = {row[1] for row in self._conn.execute("PRAGMA table_info(games)")}
        for name, sql_type in self._ADDED_COLUMNS:
            if name not in existing:
                self._conn.execute(f"ALTER TABLE games ADD COLUMN {name} {sql_type}")

    def close(self) -> None:
        """Release the connection. Safe to call twice."""
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    @staticmethod
    def _dump(game: GameState) -> str:
        return json.dumps(
            [{"guess": a.guess, "colours": [str(c) for c in a.colours]} for a in game.attempts]
        )

    def _load(self, row: sqlite3.Row | tuple) -> GameState:
        target, max_attempts, attempts_json, started_at, finished_at = row
        attempts = [
            Attempt(guess=a["guess"], colours=[Colour(c) for c in a["colours"]])
            for a in json.loads(attempts_json)
        ]
        return GameState(
            target=target,
            vocabulary=self._vocabulary_for(len(target)),
            max_attempts=max_attempts,
            attempts=attempts,
            started_at=started_at,
            finished_at=finished_at,
        )

    def create(self, game: GameState, owner: str | None = None) -> str:
        game_id = secrets.token_urlsafe(16)
        now = self._clock()
        with self._lock:
            self._purge(now)
            self._conn.execute(
                "INSERT INTO games"
                " (id, target, max_attempts, attempts, touched_at, started_at, finished_at,"
                " owner_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    game_id,
                    game.target,
                    game.max_attempts,
                    self._dump(game),
                    now,
                    game.started_at,
                    game.finished_at,
                    owner,
                ),
            )
            self._enforce_capacity()
        return game_id

    def get(self, game_id: str, viewer: str | None = None) -> GameState | None:
        now = self._clock()
        with self._lock:
            row = self._conn.execute(
                "SELECT target, max_attempts, attempts, started_at, finished_at, touched_at,"
                " owner_id FROM games WHERE id = ?",
                (game_id,),
            ).fetchone()
            if row is None or not _visible(row[6], viewer):
                return None
            if now - row[5] > self._ttl:
                self._conn.execute("DELETE FROM games WHERE id = ?", (game_id,))
                return None
            try:
                game = self._load(row[:5])
            except (ValueError, KeyError, json.JSONDecodeError):
                # The row outlived the word lists it was written against: its
                # length is no longer installed, or its target is no longer a
                # legal word. Unplayable, not a server fault, so drop it and
                # let the caller see an ordinary 404.
                self._conn.execute("DELETE FROM games WHERE id = ?", (game_id,))
                return None
            self._conn.execute("UPDATE games SET touched_at = ? WHERE id = ?", (now, game_id))
            return game

    def save(self, game_id: str, game: GameState) -> None:
        """Write a mutated game back. Silently ignores an unknown id."""
        with self._lock:
            self._conn.execute(
                "UPDATE games SET attempts = ?, touched_at = ?, started_at = ?, finished_at = ?"
                " WHERE id = ?",
                (self._dump(game), self._clock(), game.started_at, game.finished_at, game_id),
            )

    def delete(self, game_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM games WHERE id = ?", (game_id,))

    def _purge(self, now: float) -> None:
        self._conn.execute("DELETE FROM games WHERE touched_at < ?", (now - self._ttl,))

    def _enforce_capacity(self) -> None:
        self._conn.execute(
            "DELETE FROM games WHERE id IN ("
            "  SELECT id FROM games ORDER BY touched_at DESC LIMIT -1 OFFSET ?"
            ")",
            (self._max_games,),
        )

    def __len__(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
