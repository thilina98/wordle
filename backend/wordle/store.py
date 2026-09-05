"""Game persistence.

In-memory today. Anything that needs a game goes through the GameStore
protocol, so a Redis or database implementation drops in without touching the
API layer.
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
    """Storage for games in progress."""

    def create(self, game: GameState) -> str:
        """Store a game and return its id."""
        ...

    def get(self, game_id: str) -> GameState | None:
        """Fetch a live game, or None if it is unknown or expired."""
        ...

    def save(self, game_id: str, game: GameState) -> None:
        """Persist changes to a game already in the store."""
        ...

    def delete(self, game_id: str) -> None:
        """Remove a game. Does nothing if it is already gone."""
        ...


@dataclass(slots=True)
class _Entry:
    game: GameState
    touched_at: float


class InMemoryGameStore:
    """Process-local store with a sliding TTL and an LRU capacity bound.

    Both limits exist so abandoned games cannot grow without limit. Single
    process only: with more than one worker, a game is only visible to the
    worker that created it.
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
        self._entries: OrderedDict[str, _Entry] = OrderedDict()

    def create(self, game: GameState) -> str:
        self._purge_expired()
        game_id = secrets.token_urlsafe(16)
        self._entries[game_id] = _Entry(game=game, touched_at=self._clock())
        # Drop the least recently used until we are back within capacity.
        while len(self._entries) > self._max_games:
            self._entries.popitem(last=False)
        return game_id

    def get(self, game_id: str) -> GameState | None:
        entry = self._entries.get(game_id)
        if entry is None:
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
        self._entries.pop(game_id, None)

    def _purge_expired(self) -> None:
        cutoff = self._clock() - self._ttl
        expired = [gid for gid, e in self._entries.items() if e.touched_at < cutoff]
        for game_id in expired:
            del self._entries[game_id]

    def __len__(self) -> int:
        return len(self._entries)


class SqliteGameStore:
    """Games on disk, so they outlive the process that created them.

    Point this at a mounted volume and a container can be destroyed and
    rebuilt without anyone losing the board they were part way through.

    Unlike the in-memory store this one keeps copies, not references, so a
    mutated game has to be handed back with `save`.
    """

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS games (
            id           TEXT PRIMARY KEY,
            target       TEXT    NOT NULL,
            max_attempts INTEGER NOT NULL,
            attempts     TEXT    NOT NULL,
            touched_at   REAL    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS games_touched_at ON games (touched_at);
    """

    def __init__(
        self,
        path: Path,
        vocabulary: Collection[str],
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_games: int = DEFAULT_MAX_GAMES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = Path(path)
        self._vocabulary = vocabulary
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
        target, max_attempts, attempts_json = row
        attempts = [
            Attempt(guess=a["guess"], colours=[Colour(c) for c in a["colours"]])
            for a in json.loads(attempts_json)
        ]
        return GameState(
            target=target,
            vocabulary=self._vocabulary,
            max_attempts=max_attempts,
            attempts=attempts,
        )

    def create(self, game: GameState) -> str:
        game_id = secrets.token_urlsafe(16)
        now = self._clock()
        with self._lock:
            self._purge(now)
            self._conn.execute(
                "INSERT INTO games (id, target, max_attempts, attempts, touched_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (game_id, game.target, game.max_attempts, self._dump(game), now),
            )
            self._enforce_capacity()
        return game_id

    def get(self, game_id: str) -> GameState | None:
        now = self._clock()
        with self._lock:
            row = self._conn.execute(
                "SELECT target, max_attempts, attempts, touched_at FROM games WHERE id = ?",
                (game_id,),
            ).fetchone()
            if row is None:
                return None
            if now - row[3] > self._ttl:
                self._conn.execute("DELETE FROM games WHERE id = ?", (game_id,))
                return None
            self._conn.execute("UPDATE games SET touched_at = ? WHERE id = ?", (now, game_id))
            return self._load(row[:3])

    def save(self, game_id: str, game: GameState) -> None:
        """Write a mutated game back. Silently ignores an unknown id."""
        with self._lock:
            self._conn.execute(
                "UPDATE games SET attempts = ?, touched_at = ? WHERE id = ?",
                (self._dump(game), self._clock(), game_id),
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
