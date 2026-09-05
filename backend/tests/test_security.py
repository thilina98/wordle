"""Contract tests for password checking, throttling and access tokens."""

import time

import pytest

from wordle.security import (
    LoginThrottle,
    TokenError,
    bearer_token,
    issue_token,
    verify_password,
    verify_token,
)


class TestVerifyPassword:
    def test_accepts_the_right_password(self):
        assert verify_password("hunter2", "hunter2") is True

    def test_rejects_the_wrong_password(self):
        assert verify_password("nope", "hunter2") is False

    def test_is_case_and_whitespace_sensitive(self):
        assert verify_password("Hunter2", "hunter2") is False
        assert verify_password("hunter2 ", "hunter2") is False

    def test_rejects_empty_candidate(self):
        assert verify_password("", "hunter2") is False

    def test_rejects_everything_when_no_password_is_configured(self):
        # Fail closed: a blank configured password must not open the door.
        assert verify_password("", "") is False
        assert verify_password("anything", "") is False


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestLoginThrottle:
    def test_starts_unlocked(self):
        assert LoginThrottle().is_locked("1.2.3.4") is False

    def test_locks_after_the_failure_limit(self):
        throttle = LoginThrottle(max_failures=3, lockout_seconds=60, clock=FakeClock())
        for _ in range(3):
            throttle.record_failure("1.2.3.4")
        assert throttle.is_locked("1.2.3.4") is True

    def test_stays_unlocked_below_the_limit(self):
        throttle = LoginThrottle(max_failures=3, clock=FakeClock())
        throttle.record_failure("1.2.3.4")
        throttle.record_failure("1.2.3.4")
        assert throttle.is_locked("1.2.3.4") is False

    def test_locks_each_client_separately(self):
        throttle = LoginThrottle(max_failures=1, clock=FakeClock())
        throttle.record_failure("1.2.3.4")
        assert throttle.is_locked("1.2.3.4") is True
        assert throttle.is_locked("5.6.7.8") is False

    def test_lock_expires(self):
        clock = FakeClock()
        throttle = LoginThrottle(max_failures=1, lockout_seconds=60, clock=clock)
        throttle.record_failure("1.2.3.4")
        clock.advance(61)
        assert throttle.is_locked("1.2.3.4") is False

    def test_success_clears_the_record(self):
        throttle = LoginThrottle(max_failures=2, clock=FakeClock())
        throttle.record_failure("1.2.3.4")
        throttle.record_success("1.2.3.4")
        throttle.record_failure("1.2.3.4")
        assert throttle.is_locked("1.2.3.4") is False

    def test_reports_seconds_until_unlock(self):
        clock = FakeClock()
        throttle = LoginThrottle(max_failures=1, lockout_seconds=60, clock=clock)
        throttle.record_failure("1.2.3.4")
        clock.advance(20)
        assert throttle.retry_after("1.2.3.4") == pytest.approx(40, abs=1)

    def test_retry_after_is_zero_when_unlocked(self):
        assert LoginThrottle().retry_after("1.2.3.4") == 0


class TestTokens:
    KEY = "a-secret-key-long-enough"

    def test_a_freshly_issued_token_verifies(self):
        verify_token(issue_token(self.KEY), self.KEY, max_age=60)

    def test_rejects_a_token_from_another_key(self):
        with pytest.raises(TokenError):
            verify_token(issue_token("some-other-secret-key"), self.KEY, max_age=60)

    def test_rejects_a_tampered_payload(self):
        # Mutate the payload, not the trailing signature character: base64
        # carries spare bits at the end, so flipping the last character can
        # decode to the same bytes and the test would pass by luck.
        payload, timestamp, signature = issue_token(self.KEY).split(".")
        swapped = ("A" if payload[0] != "A" else "B") + payload[1:]
        with pytest.raises(TokenError):
            verify_token(f"{swapped}.{timestamp}.{signature}", self.KEY, max_age=60)

    def test_rejects_a_tampered_signature(self):
        payload, timestamp, signature = issue_token(self.KEY).split(".")
        with pytest.raises(TokenError):
            verify_token(f"{payload}.{timestamp}.{'x' * len(signature)}", self.KEY, max_age=60)

    def test_rejects_gibberish(self):
        with pytest.raises(TokenError):
            verify_token("not-a-token", self.KEY, max_age=60)

    def test_rejects_an_expired_token(self):
        token = issue_token(self.KEY)
        real_time = time.time
        try:
            time.time = lambda: real_time() + 120
            with pytest.raises(TokenError, match="expired"):
                verify_token(token, self.KEY, max_age=60)
        finally:
            time.time = real_time

    def test_tokens_carry_no_secret(self):
        assert "granted" not in issue_token(self.KEY)


class TestBearerHeader:
    def test_reads_a_bearer_token(self):
        assert bearer_token("Bearer abc123") == "abc123"

    def test_scheme_is_case_insensitive(self):
        assert bearer_token("bearer abc123") == "abc123"

    def test_rejects_a_missing_header(self):
        with pytest.raises(TokenError):
            bearer_token(None)

    def test_rejects_another_scheme(self):
        with pytest.raises(TokenError):
            bearer_token("Basic abc123")

    def test_rejects_an_empty_token(self):
        for header in ("Bearer", "Bearer ", ""):
            with pytest.raises(TokenError):
                bearer_token(header)
