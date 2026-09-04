"""Site access: one shared password, no user accounts.

The password is checked server side only and never reaches the browser. A
signed session cookie carries the result.
"""

from __future__ import annotations

import hmac
import time
from collections.abc import Callable
from dataclasses import dataclass

SESSION_KEY = "authenticated"

DEFAULT_MAX_FAILURES = 10
DEFAULT_LOCKOUT_SECONDS = 300


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
