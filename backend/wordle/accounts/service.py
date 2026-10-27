"""The accounts module: from an Authorization header to a player."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

from .model import Credential, Identity, Player, Profile
from .repository import PlayerRepository

log = logging.getLogger("wordle.accounts")


class AuthenticationError(Exception):
    """The credentials were sent, and they are not good. Maps to 401.

    Never raised for a request with no credentials: that is an anonymous
    player, not a failed sign-in.
    """


class AccountsUnavailable(Exception):
    """The identity provider or the player store could not be reached. Maps to 503."""


class IdentityProvider(Protocol):
    """A sign-in service: proves who sent a token, and can close accounts.

    The seam an identity service plugs into. `OidcProvider` works with any
    OpenID Connect service but cannot close accounts, because the standard
    has no way to; a provider-specific class such as `Auth0Provider` adds that.
    """

    def verify(self, token: str) -> Credential:
        """Check the token and say whose it is and when it was issued.

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

    def delete_account(self, identity: Identity) -> bool:
        """Close this person's account at the provider.

        True when the account is gone (including already gone). False when
        this provider cannot close accounts, or the identity belongs to a
        different provider: nothing was done. Raises AccountsUnavailable if
        the provider was asked and failed.
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
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._provider = provider
        self._players = players
        self._link_verified_emails = link_verified_emails
        self._clock = clock

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
        credential = self._provider.verify(token)
        identity = credential.identity

        player = self._players.find(identity)
        if player is not None:
            return player

        # A token from before the player deleted their account must not
        # bring them back as a new player. Signing in again afresh is fine.
        deleted_at = self._players.deleted_at(identity)
        if deleted_at is not None and credential.issued_at <= deleted_at:
            raise AuthenticationError("This account was deleted")

        profile = self._provider.profile(token)
        link_email = profile.verified_email if self._link_verified_emails else None
        return self._players.register(identity, profile, link_email)

    def delete(self, player: Player) -> None:
        """Delete the player: their accounts at the provider, then our records.

        Provider accounts go first, and a failure there stops everything, so
        the player can simply try again. Deleting at the provider is
        repeatable: an account already gone counts as deleted.

        Tokens issued before this moment stop working for this player. A
        provider that cannot close accounts leaves them open; that is logged.
        """
        for identity in self._players.identities(player.player_id):
            if not self._provider.delete_account(identity):
                log.warning(
                    "Account at %s left open for deleted player %s: "
                    "this provider cannot close accounts",
                    identity.issuer,
                    player.player_id,
                )
        self._players.delete(player.player_id, deleted_at=self._clock())

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
