"""Where players are remembered. The port, and the in-memory adapter.

The Postgres adapter lives in `postgres.py` so that importing this package
never needs a database driver.
"""

from __future__ import annotations

import threading
import uuid
from typing import Protocol

from .model import Identity, Player, Profile


class PlayerRepository(Protocol):
    """Storage for players and the identities that sign them in.

    Both methods raise `AccountsUnavailable` when the store cannot be reached.
    """

    def find(self, identity: Identity) -> Player | None:
        """The player this identity signs in, or None if it is new."""
        ...

    def register(self, identity: Identity, profile: Profile, link_email: str | None) -> Player:
        """Attach a new identity to a player, and return that player.

        If `link_email` is given and an existing player already has an identity
        whose *verified* email matches it (case-insensitively), the identity
        joins that player. Otherwise a new player is created.

        Idempotent: if the identity is already registered, by this call or a
        racing one, its existing player is returned and nothing is created.
        """
        ...

    def delete(self, player_id: str) -> None:
        """Remove a player and every identity that signs them in.

        Does nothing if the player is already gone.
        """
        ...


class InMemoryPlayerRepository:
    """Process-local players. For tests, and for running without a database."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._players: dict[str, Player] = {}
        self._identities: dict[Identity, str] = {}
        #: identity -> its verified email, lowercased, for linking.
        self._verified_emails: dict[Identity, str] = {}

    def find(self, identity: Identity) -> Player | None:
        with self._lock:
            player_id = self._identities.get(identity)
            return self._players[player_id] if player_id else None

    def register(self, identity: Identity, profile: Profile, link_email: str | None) -> Player:
        with self._lock:
            existing = self._identities.get(identity)
            if existing:
                return self._players[existing]

            player_id = self._player_with_email(link_email) if link_email else None
            if player_id is None:
                player_id = str(uuid.uuid4())
                self._players[player_id] = Player(player_id, profile.display_name())

            self._identities[identity] = player_id
            if profile.verified_email:
                self._verified_emails[identity] = profile.verified_email.lower()
            return self._players[player_id]

    def delete(self, player_id: str) -> None:
        with self._lock:
            self._players.pop(player_id, None)
            gone = [i for i, owner in self._identities.items() if owner == player_id]
            for identity in gone:
                del self._identities[identity]
                self._verified_emails.pop(identity, None)

    def _player_with_email(self, email: str) -> str | None:
        """Caller holds the lock. Oldest matching identity wins, as in Postgres."""
        wanted = email.lower()
        for identity, verified in self._verified_emails.items():
            if verified == wanted:
                return self._identities[identity]
        return None

    def __len__(self) -> int:
        with self._lock:
            return len(self._players)
