"""Contract tests for password checking and login throttling."""

import pytest

from wordle.security import LoginThrottle, verify_password


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
