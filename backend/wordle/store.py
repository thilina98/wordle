"""Game persistence.

Two adapters behind the GameStore protocol: SQLite on a mounted volume, which
is the default, and an in-memory store for tests and throwaway runs. Anything
that needs a game goes through the protocol, so a third (Redis, say) drops in
without touching the API layer.

Besides games in progress, the store holds signed-in players' games that are
over but not yet written to the statistics database. They wait here, safe
from expiry, until something records them: so a statistics outage delays a
result, and never loses one.
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .game import Attempt, Colour, Difficulty, GameState, difficulty_of

log = logging.getLogger("wordle.store")

DEFAULT_TTL_SECONDS = 60 * 60 * 4
DEFAULT_MAX_GAMES = 10_000

#: A game left with fewer guesses than this is not worth recording. One guess
#: tells the player almost nothing, so walking away from it is not a loss.
MIN_GUESSES_TO_ABANDON = 2

# What happened to an owned game's result. No state means there is nothing to
# record yet: the game is still being played, or was never owned.
_PENDING = "pending"
_RECORDED = "recorded"


@dataclass(frozen=True, slots=True)
class PendingResult:
    """An owned game waiting to be recorded: finished, or abandoned mid-play."""

    game_id: str
    owner: str
    game: GameState
    #: When it ended: its last guess, or when it was abandoned.
    ended_at: float
    abandoned: bool


class GameStore(Protocol):
    """Storage for games in progress, and for results not yet recorded.

    A game may have an owner: the player who started it while signed in. An
    owned game is visible to its owner only. An unowned game, started
    anonymously, is visible to anyone holding its id, as every game was before
    accounts existed.

    An owned game becomes pending -- waiting to be recorded -- when it is
    saved finished, or when it is abandoned with at least two guesses made.
    Abandoning happens when its owner starts another game of the same word
    length and difficulty (`abandon_open_games`), or when it expires or is
    evicted. A pending game is never expired or evicted. An abandoned game can
    no longer be fetched or played.
    """

    def create(self, game: GameState, owner: str | None = None) -> str:
        """Store a game and return its id. `owner` is a player id, or None."""
        ...

    def get(self, game_id: str, viewer: str | None = None) -> GameState | None:
        """Fetch a live game that `viewer` may see.

        None if the game is unknown, expired, abandoned, or owned by someone
        other than `viewer`. These look the same on purpose: a game id must
        not reveal whether someone else's game exists.
        """
        ...

    def save(self, game_id: str, game: GameState) -> None:
        """Persist changes to a game already in the store.

        An owned game saved finished becomes pending.
        """
        ...

    def delete(self, game_id: str) -> None:
        """Remove a game. Does nothing if it is already gone."""
        ...

    def delete_owned_by(self, owner: str) -> int:
        """Remove every game this player owns, pending or not. Returns how many went."""
        ...

    def abandon_open_games(self, owner: str, word_length: int, difficulty: Difficulty) -> int:
        """Abandon this player's unfinished games at this word length and difficulty.

        Games with fewer than two guesses are left as they are. Returns how
        many were abandoned.
        """
        ...

    def pending_results(self, limit: int = 100) -> list[PendingResult]:
        """Games waiting to be recorded, the earliest ended first.

        Earliest first because the order results are recorded in is the order
        streaks are counted in.
        """
        ...

    def mark_recorded(self, game_id: str) -> None:
        """The game's result is safely recorded.

        A finished game stays, so its board can still be shown, and expires as
        usual. An abandoned game goes.
        """
        ...


def _visible(owner: str | None, viewer: str | None) -> bool:
    """Anyone may see an unowned game; only its owner may see an owned one."""
    return owner is None or owner == viewer


def _abandonable(owner: str | None, game: GameState, state: str | None) -> bool:
    """An owned game, still being played, with enough guesses made to count."""
    return (
        owner is not None
        and state is None
        and not game.is_over
        and len(game.attempts) >= MIN_GUESSES_TO_ABANDON
    )


@dataclass(slots=True)
class _Entry:
    game: GameState
    touched_at: float
    owner: str | None = None
    #: Wall-clock time of the last touch. `touched_at` runs on the store's own
    #: clock, which need not be a wall clock; this is what an abandoned game
    #: records as its end.
    touched_wall: float = 0.0
    state: str | None = None
    abandoned_at: float | None = None


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
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_games = max_games
        self._clock = clock
        self._wall_clock = wall_clock
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, _Entry] = OrderedDict()

    def create(self, game: GameState, owner: str | None = None) -> str:
        game_id = secrets.token_urlsafe(16)
        with self._lock:
            self._purge_expired()
            self._entries[game_id] = _Entry(
                game=game, touched_at=self._clock(), owner=owner, touched_wall=self._wall_clock()
            )
            # Retire the least recently used until we are back within capacity.
            # Pending games are kept, so this can stop short of the bound.
            for old_id in list(self._entries)[: max(0, len(self._entries) - self._max_games)]:
                self._retire(old_id)
        return game_id

    def get(self, game_id: str, viewer: str | None = None) -> GameState | None:
        with self._lock:
            entry = self._entries.get(game_id)
            if entry is None or entry.abandoned_at is not None:
                return None
            if not _visible(entry.owner, viewer):
                return None
            now = self._clock()
            if now - entry.touched_at > self._ttl:
                self._retire(game_id)
                return None
            entry.touched_at = now
            entry.touched_wall = self._wall_clock()
            self._entries.move_to_end(game_id)
            return entry.game

    def save(self, game_id: str, game: GameState) -> None:
        """`get` handed out the live object, so only the record state can change."""
        with self._lock:
            entry = self._entries.get(game_id)
            if entry is not None and entry.owner is not None and entry.state is None:
                if game.is_over:
                    entry.state = _PENDING

    def delete(self, game_id: str) -> None:
        with self._lock:
            self._entries.pop(game_id, None)

    def delete_owned_by(self, owner: str) -> int:
        with self._lock:
            owned = [gid for gid, e in self._entries.items() if e.owner == owner]
            for game_id in owned:
                del self._entries[game_id]
            return len(owned)

    def abandon_open_games(self, owner: str, word_length: int, difficulty: Difficulty) -> int:
        with self._lock:
            now = self._wall_clock()
            abandoned = 0
            for entry in self._entries.values():
                if (
                    entry.owner == owner
                    and entry.abandoned_at is None
                    and entry.game.word_length == word_length
                    and entry.game.difficulty == difficulty
                    and _abandonable(entry.owner, entry.game, entry.state)
                ):
                    entry.state, entry.abandoned_at = _PENDING, now
                    abandoned += 1
            return abandoned

    def pending_results(self, limit: int = 100) -> list[PendingResult]:
        with self._lock:
            pending = [
                PendingResult(
                    game_id=game_id,
                    owner=entry.owner,
                    game=entry.game,
                    ended_at=_ended_at(entry),
                    abandoned=entry.abandoned_at is not None,
                )
                for game_id, entry in self._entries.items()
                if entry.state == _PENDING
            ]
        return sorted(pending, key=lambda p: p.ended_at)[:limit]

    def mark_recorded(self, game_id: str) -> None:
        with self._lock:
            entry = self._entries.get(game_id)
            if entry is None or entry.state != _PENDING:
                return
            if entry.abandoned_at is not None:
                del self._entries[game_id]
            else:
                entry.state = _RECORDED

    def _retire(self, game_id: str) -> None:
        """Expire or evict one game. Caller holds the lock.

        A game that is abandoned by this is kept for recording; a pending one
        is kept as it is; anything else goes.
        """
        entry = self._entries[game_id]
        if _abandonable(entry.owner, entry.game, entry.state):
            entry.state, entry.abandoned_at = _PENDING, entry.touched_wall
        if entry.state != _PENDING:
            del self._entries[game_id]

    def _purge_expired(self) -> None:
        """Caller holds the lock."""
        cutoff = self._clock() - self._ttl
        for game_id in [gid for gid, e in self._entries.items() if e.touched_at < cutoff]:
            self._retire(game_id)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


def _ended_at(entry: _Entry) -> float:
    if entry.abandoned_at is not None:
        return entry.abandoned_at
    if entry.game.finished_at is not None:
        return entry.game.finished_at
    return entry.touched_wall


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
            owner_id     TEXT,
            record_state TEXT,
            abandoned_at REAL
        );
        CREATE INDEX IF NOT EXISTS games_touched_at ON games (touched_at);
    """

    #: Columns added after the table shipped. A database written by an older
    #: build has the table already, so CREATE TABLE IF NOT EXISTS skips it and
    #: these have to be put on by hand. Games in flight keep playing; they just
    #: score as untimed.
    #: owner_id arrived with accounts; a game from before it is unowned.
    #: record_state and abandoned_at arrived with statistics; a game from
    #: before them has nothing to record until it is saved again.
    _ADDED_COLUMNS = (
        ("started_at", "REAL"),
        ("finished_at", "REAL"),
        ("owner_id", "TEXT"),
        ("record_state", "TEXT"),
        ("abandoned_at", "REAL"),
    )

    #: Columns `_load` reads, in its order.
    _GAME_COLUMNS = "target, max_attempts, attempts, started_at, finished_at"

    #: An owned game, still being played, with enough guesses to be worth recording.
    _ABANDONABLE = (
        "owner_id IS NOT NULL AND record_state IS NULL AND finished_at IS NULL"
        f" AND json_array_length(attempts) >= {MIN_GUESSES_TO_ABANDON}"
    )

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
                f"SELECT {self._GAME_COLUMNS}, touched_at, owner_id, abandoned_at"
                " FROM games WHERE id = ?",
                (game_id,),
            ).fetchone()
            if row is None or row[7] is not None or not _visible(row[6], viewer):
                return None
            if now - row[5] > self._ttl:
                self._purge(now)
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
                "UPDATE games SET attempts = ?, touched_at = ?, started_at = ?, finished_at = ?,"
                " record_state = CASE"
                "   WHEN record_state IS NULL AND owner_id IS NOT NULL AND ? THEN ?"
                "   ELSE record_state END"
                " WHERE id = ?",
                (
                    self._dump(game),
                    self._clock(),
                    game.started_at,
                    game.finished_at,
                    game.is_over,
                    _PENDING,
                    game_id,
                ),
            )

    def delete(self, game_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM games WHERE id = ?", (game_id,))

    def delete_owned_by(self, owner: str) -> int:
        with self._lock:
            return self._conn.execute("DELETE FROM games WHERE owner_id = ?", (owner,)).rowcount

    def abandon_open_games(self, owner: str, word_length: int, difficulty: Difficulty) -> int:
        now = self._clock()
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, max_attempts FROM games"
                f" WHERE owner_id = ? AND length(target) = ? AND {self._ABANDONABLE}",
                (owner, word_length),
            ).fetchall()
            # Difficulty is a label worked out from the shape, so it is
            # filtered here rather than in SQL: the mapping lives in one place.
            ids = [
                gid for gid, allowed in rows if difficulty_of(word_length, allowed) == difficulty
            ]
            for game_id in ids:
                self._conn.execute(
                    "UPDATE games SET record_state = ?, abandoned_at = ? WHERE id = ?",
                    (_PENDING, now, game_id),
                )
            return len(ids)

    def pending_results(self, limit: int = 100) -> list[PendingResult]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id, owner_id, {self._GAME_COLUMNS}, abandoned_at, touched_at FROM games"
                " WHERE record_state = ?"
                " ORDER BY coalesce(abandoned_at, finished_at, touched_at) LIMIT ?",
                (_PENDING, limit),
            ).fetchall()
            pending = []
            for game_id, owner, *game_row, abandoned_at, touched_at in rows:
                try:
                    game = self._load(game_row)
                except (ValueError, KeyError, json.JSONDecodeError):
                    # Its word list is gone, so it cannot be rebuilt or recorded.
                    log.warning("Dropping unrecordable game %s: its word list is gone", game_id)
                    self._conn.execute("DELETE FROM games WHERE id = ?", (game_id,))
                    continue
                ended_at = abandoned_at if abandoned_at is not None else game.finished_at
                pending.append(
                    PendingResult(
                        game_id=game_id,
                        owner=owner,
                        game=game,
                        ended_at=ended_at if ended_at is not None else touched_at,
                        abandoned=abandoned_at is not None,
                    )
                )
            return pending

    def mark_recorded(self, game_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM games WHERE id = ? AND record_state = ? AND abandoned_at IS NOT NULL",
                (game_id, _PENDING),
            )
            self._conn.execute(
                "UPDATE games SET record_state = ? WHERE id = ? AND record_state = ?",
                (_RECORDED, game_id, _PENDING),
            )

    def _retire(self, where: str, params: tuple) -> None:
        """Expire or evict the games matching `where`. Caller holds the lock.

        Games this abandons are kept for recording, ending when they were last
        touched; pending games are kept as they are; the rest go.
        """
        self._conn.execute(
            "UPDATE games SET record_state = ?, abandoned_at = touched_at"
            f" WHERE ({where}) AND {self._ABANDONABLE}",
            (_PENDING, *params),
        )
        self._conn.execute(
            f"DELETE FROM games WHERE ({where}) AND record_state IS NOT ?", (*params, _PENDING)
        )

    def _purge(self, now: float) -> None:
        self._retire("touched_at < ?", (now - self._ttl,))

    def _enforce_capacity(self) -> None:
        # Pending games are kept, so this can stop short of the bound.
        self._retire(
            "id IN (SELECT id FROM games ORDER BY touched_at DESC LIMIT -1 OFFSET ?)",
            (self._max_games,),
        )

    def __len__(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
