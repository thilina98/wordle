"""The accounts module: from an Authorization header to a player."""

from __future__ import annotations

from typing import Protocol

from .model import Identity, Player, Profile
from .repository import PlayerRepository


class AuthenticationError(Exception):
    """The credentials were sent, and they are not good. Maps to 401.

    Never raised for a request with no credentials: that is an anonymous
    player, not a failed sign-in.
    """


class AccountsUnavailable(Exception):
    """The identity provider or the player store could not be reached. Maps to 503."""


class IdentityProvider(Protocol):
    """Proves who sent a token. The seam an identity service plugs into."""

    def verify(self, token: str) -> Identity:
        """Check the token and say whose it is.

        Raises AuthenticationError for a token that is malformed, forged,
        expired or meant for someone else; AccountsUnavailable if the provider
        cannot be reached to check it.
        """
        ...

    def profile(self, token: str) -> Profile:
        """Ask the provider about the token's owner. Called once per new identity.

        Raises AccountsUnavailable if the provider cannot be reached.
        """
        ...


def bearer_token(authorization: str) -> str:
    """Pull the token out of an Authorization header, or raise AuthenticationError."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("Malformed credentials")
    return token.strip()


class Accounts:
    """Says which player sent a request.

    Signing up is not a separate step. The first time an identity is seen it is
    registered: joined to an existing player whose verified email matches, when
    `link_verified_emails` is on, or given a new player otherwise.
    """

    def __init__(
        self,
        provider: IdentityProvider,
        players: PlayerRepository,
        *,
        link_verified_emails: bool = True,
    ) -> None:
        self._provider = provider
        self._players = players
        self._link_verified_emails = link_verified_emails

    def identify(self, authorization: str | None) -> Player | None:
        """The player behind an Authorization header.

        None for no header at all: an anonymous player. Raises
        AuthenticationError for bad credentials and AccountsUnavailable when a
        dependency is down. Bad credentials are never downgraded to anonymous,
        so a client with a stale token finds out instead of silently playing
        games that will not be saved to its account.
        """
        if authorization is None:
            return None
        token = bearer_token(authorization)
        identity = self._provider.verify(token)

        player = self._players.find(identity)
        if player is not None:
            return player

        profile = self._provider.profile(token)
        link_email = profile.verified_email if self._link_verified_emails else None
        return self._players.register(identity, profile, link_email)

    def delete(self, player: Player) -> None:
        """Remove the player and all their sign-in identities.

        Only our records go: the account at the identity provider stays, so
        signing in there again creates a new, empty player.
        """
        self._players.delete(player.player_id)

    def close(self) -> None:
        """Release the player store's connections, if it holds any."""
        close = getattr(self._players, "close", None)
        if close:
            close()


class SignInDisabled:
    """Stands in for Accounts when no identity provider is configured.

    Anonymous play works as normal; anyone presenting credentials is told
    sign-in is off rather than being quietly treated as anonymous.
    """

    def identify(self, authorization: str | None) -> Player | None:
        if authorization is None:
            return None
        raise AuthenticationError("Sign-in is not enabled on this server")

    def delete(self, player: Player) -> None:
        raise AuthenticationError("Sign-in is not enabled on this server")
