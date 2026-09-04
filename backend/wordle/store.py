"""Game persistence.

In-memory today. Anything that needs a game goes through the GameStore
protocol, so a Redis or database implementation drops in without touching the
API layer.
"""

from __future__ import annotations

import secrets
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .game import GameState

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

    def delete(self, game_id: str) -> None:
        self._entries.pop(game_id, None)

    def _purge_expired(self) -> None:
        cutoff = self._clock() - self._ttl
        expired = [gid for gid, e in self._entries.items() if e.touched_at < cutoff]
        for game_id in expired:
            del self._entries[game_id]

    def __len__(self) -> int:
        return len(self._entries)
