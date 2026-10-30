"""Test adapter for the IdentityProvider seam.

Stands in for a real identity provider: tokens are plain strings registered
up front, so tests can sign in as anyone without keys or a network.
"""

from __future__ import annotations

import itertools
import time

from wordle.accounts import (
    AccountsUnavailable,
    AuthenticationError,
    Credential,
    Identity,
    Profile,
)

ISSUER = "https://id.example.test/"


class FakeIdentityProvider:
    def __init__(self, issuer: str = ISSUER) -> None:
        self.issuer = issuer
        self.down = False
        self.profile_calls = 0
        #: When True, delete_account raises, as if the provider were down.
        self.delete_fails = False
        #: When False, behaves like a provider that cannot close accounts.
        self.can_delete = True
        self.deleted: list[Identity] = []
        self._people: dict[str, tuple[Credential, Profile]] = {}
        self._serial = itertools.count()

    def person(
        self,
        subject: str,
        *,
        email: str | None = None,
        verified: bool = False,
        name: str | None = None,
    ) -> str:
        """Sign someone in and return their token, issued now.

        Each call is a new sign-in with a new token, like a real provider.
        """
        token = f"token-{self.issuer}-{subject}-{next(self._serial)}"
        self._people[token] = (
            Credential(Identity(self.issuer, subject), issued_at=time.time()),
            Profile(email=email, email_verified=verified, name=name),
        )
        return token

    def verify(self, token: str) -> Credential:
        if self.down:
            raise AccountsUnavailable("provider down")
        if token not in self._people:
            raise AuthenticationError("Invalid token")
        return self._people[token][0]

    def delete_account(self, identity: Identity) -> bool:
        if identity.issuer != self.issuer or not self.can_delete:
            return False
        if self.delete_fails:
            raise AccountsUnavailable("provider down")
        self.deleted.append(identity)
        return True

    def profile(self, token: str) -> Profile:
        if self.down:
            raise AccountsUnavailable("provider down")
        self.profile_calls += 1
        return self._people[token][1]
