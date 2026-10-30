"""The values that cross the accounts seams. Plain data, no behaviour."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

DISPLAY_NAME_MAX = 64


@dataclass(frozen=True, slots=True)
class Identity:
    """One sign-in method, as the identity provider names it.

    `issuer` is the provider; `subject` is its stable id for this person, unique
    within that issuer only. The pair is what a player is found by. A player can
    own several: email-and-password, Google and GitHub are three identities.
    """

    issuer: str
    subject: str

    def fingerprint(self) -> str:
        """A one-way hash of this identity, for remembering it without keeping it.

        Used to note that a deleted player's sign-in existed, without storing
        the provider's id for that person.
        """
        return hashlib.sha256(f"{self.issuer}\0{self.subject}".encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Credential:
    """A checked token: whose it is, and when the provider issued it."""

    identity: Identity
    #: Seconds since the epoch, from the token's own `iat`.
    issued_at: float


@dataclass(frozen=True, slots=True)
class Profile:
    """What the provider says about the person behind an identity.

    Only asked for the first time an identity is seen. Every field may be
    missing: GitHub accounts, for one, can hide their email.
    """

    email: str | None = None
    email_verified: bool = False
    name: str | None = None

    @property
    def verified_email(self) -> str | None:
        """The email, only if the provider vouches that this person owns it."""
        return self.email if self.email and self.email_verified else None

    def display_name(self) -> str:
        """A name to show, from whatever the provider shared. Never empty."""
        candidates = (self.name, self.email.split("@", 1)[0] if self.email else None)
        for candidate in candidates:
            if candidate and candidate.strip():
                return candidate.strip()[:DISPLAY_NAME_MAX]
        return "Player"


@dataclass(frozen=True, slots=True)
class Player:
    """Someone with an account. `player_id` is ours, not the provider's.

    Keeping our own id is what makes the provider swappable: stats and games
    hang off `player_id`, and only the identities table knows a provider exists.
    """

    player_id: str
    display_name: str
