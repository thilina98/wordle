"""Test adapter for the IdentityProvider seam.

Stands in for a real identity provider: tokens are plain strings registered
up front, so tests can sign in as anyone without keys or a network.
"""

from __future__ import annotations

from wordle.accounts import AccountsUnavailable, AuthenticationError, Identity, Profile

ISSUER = "https://id.example.test/"


class FakeIdentityProvider:
    def __init__(self, issuer: str = ISSUER) -> None:
        self.issuer = issuer
        self.down = False
        self.profile_calls = 0
        self._people: dict[str, tuple[Identity, Profile]] = {}

    def person(
        self,
        subject: str,
        *,
        email: str | None = None,
        verified: bool = False,
        name: str | None = None,
    ) -> str:
        """Register someone and return a token that signs them in."""
        token = f"token-{self.issuer}-{subject}"
        self._people[token] = (
            Identity(self.issuer, subject),
            Profile(email=email, email_verified=verified, name=name),
        )
        return token

    def verify(self, token: str) -> Identity:
        if self.down:
            raise AccountsUnavailable("provider down")
        if token not in self._people:
            raise AuthenticationError("Invalid token")
        return self._people[token][0]

    def profile(self, token: str) -> Profile:
        if self.down:
            raise AccountsUnavailable("provider down")
        self.profile_calls += 1
        return self._people[token][1]
