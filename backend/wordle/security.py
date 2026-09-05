"""API access: one shared password, no user accounts.

The frontend is a separate origin, so access is carried by a signed bearer
token rather than a cookie. A token proves only "someone knew the password";
it holds no identity because there is none.
"""

from __future__ import annotations

import hmac
import time
from collections.abc import Callable
from dataclasses import dataclass

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

DEFAULT_MAX_FAILURES = 10
DEFAULT_LOCKOUT_SECONDS = 300

_TOKEN_SALT = "wordle-access"
_TOKEN_SUBJECT = "granted"


def verify_password(candidate: str, expected: str) -> bool:
    """Compare in constant time so timing does not leak the password.

    Fails closed: an unset expected password rejects everything.
    """
    if not expected or not candidate:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


@dataclass(slots=True)
class _Record:
    failures: int
    locked_until: float


class LoginThrottle:
    """Per-client failure counter, to blunt password guessing.

    Process-local, so it is a speed bump rather than a guarantee. Put a real
    rate limit at the reverse proxy if the site is exposed to the internet.
    """

    def __init__(
        self,
        max_failures: int = DEFAULT_MAX_FAILURES,
        lockout_seconds: float = DEFAULT_LOCKOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_failures = max_failures
        self._lockout = lockout_seconds
        self._clock = clock
        self._records: dict[str, _Record] = {}

    def record_failure(self, client: str) -> None:
        record = self._records.setdefault(client, _Record(failures=0, locked_until=0.0))
        record.failures += 1
        if record.failures >= self._max_failures:
            record.locked_until = self._clock() + self._lockout

    def record_success(self, client: str) -> None:
        self._records.pop(client, None)

    def is_locked(self, client: str) -> bool:
        return self.retry_after(client) > 0

    def retry_after(self, client: str) -> float:
        """Seconds until this client may try again. Zero when unlocked."""
        record = self._records.get(client)
        if record is None:
            return 0.0
        remaining = record.locked_until - self._clock()
        if remaining <= 0:
            # Lock served: clear it so the client gets a fresh allowance.
            if record.locked_until:
                del self._records[client]
            return 0.0
        return remaining


class TokenError(Exception):
    """The token is missing, tampered with, or past its lifetime."""


def issue_token(secret_key: str) -> str:
    """Mint a signed token. Its age is stamped in, and checked on read."""
    return URLSafeTimedSerializer(secret_key, salt=_TOKEN_SALT).dumps(_TOKEN_SUBJECT)


def verify_token(token: str, secret_key: str, max_age: int) -> None:
    """Raise TokenError unless the token is ours and still fresh."""
    serializer = URLSafeTimedSerializer(secret_key, salt=_TOKEN_SALT)
    try:
        subject = serializer.loads(token, max_age=max_age)
    except SignatureExpired as exc:
        raise TokenError("Token expired") from exc
    except BadSignature as exc:
        raise TokenError("Invalid token") from exc
    if subject != _TOKEN_SUBJECT:
        raise TokenError("Invalid token")


def bearer_token(header: str | None) -> str:
    """Pull the token out of an Authorization header.

    Raises TokenError rather than returning empty, so a malformed header and a
    missing one fail the same way.
    """
    if not header:
        raise TokenError("Missing credentials")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise TokenError("Missing credentials")
    return token.strip()
