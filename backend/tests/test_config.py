"""Settings must fail fast rather than fall back to a guessable default."""

import pytest
from pydantic import ValidationError

from wordle.config import Settings


def test_refuses_to_start_without_a_password(monkeypatch):
    monkeypatch.delenv("WORDLE_PASSWORD", raising=False)
    monkeypatch.setenv("WORDLE_SECRET_KEY", "x" * 32)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_refuses_to_start_without_a_secret_key(monkeypatch):
    monkeypatch.setenv("WORDLE_PASSWORD", "hunter2")
    monkeypatch.delenv("WORDLE_SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_refuses_a_blank_password():
    with pytest.raises(ValidationError):
        Settings(password="", secret_key="x" * 32, _env_file=None)


def test_refuses_a_short_secret_key():
    with pytest.raises(ValidationError):
        Settings(password="hunter2", secret_key="short", _env_file=None)


def test_reads_values_from_the_environment(monkeypatch):
    monkeypatch.setenv("WORDLE_PASSWORD", "hunter2")
    monkeypatch.setenv("WORDLE_SECRET_KEY", "y" * 32)
    monkeypatch.setenv("WORDLE_MAX_ATTEMPTS", "6")
    settings = Settings(_env_file=None)
    assert settings.password == "hunter2"
    assert settings.max_attempts == 6
