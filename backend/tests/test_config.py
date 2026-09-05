"""Settings must fail fast rather than fall back to a guessable default."""

import pytest
from pydantic import ValidationError

from wordle.config import Settings


@pytest.fixture
def no_secrets(tmp_path):
    """An empty secrets directory.

    Passing None means "not provided" to pydantic-settings, which then falls
    back to the configured directory -- and a test would quietly read the
    developer's real secrets/ instead of failing.
    """
    empty = tmp_path / "no-secrets"
    empty.mkdir()
    return str(empty)


def test_refuses_to_start_without_a_password(monkeypatch, no_secrets):
    monkeypatch.delenv("WORDLE_PASSWORD", raising=False)
    monkeypatch.setenv("WORDLE_SECRET_KEY", "x" * 32)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, _secrets_dir=no_secrets)


def test_refuses_to_start_without_a_secret_key(monkeypatch, no_secrets):
    monkeypatch.setenv("WORDLE_PASSWORD", "hunter2")
    monkeypatch.delenv("WORDLE_SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, _secrets_dir=no_secrets)


def test_refuses_a_blank_password(no_secrets):
    with pytest.raises(ValidationError):
        Settings(password="", secret_key="x" * 32, _env_file=None, _secrets_dir=no_secrets)


def test_refuses_a_short_secret_key(no_secrets):
    with pytest.raises(ValidationError):
        Settings(password="hunter2", secret_key="short", _env_file=None, _secrets_dir=no_secrets)


def test_reads_values_from_the_environment(monkeypatch):
    monkeypatch.setenv("WORDLE_PASSWORD", "hunter2")
    monkeypatch.setenv("WORDLE_SECRET_KEY", "y" * 32)
    monkeypatch.setenv("WORDLE_MAX_ATTEMPTS", "6")
    settings = Settings(_env_file=None)
    assert settings.password == "hunter2"
    assert settings.max_attempts == 6


class TestAllowedOrigins:
    """CORS origins arrive as a comma-separated string from the environment."""

    ENV = {"WORDLE_PASSWORD": "hunter2", "WORDLE_SECRET_KEY": "y" * 32}

    def _settings(self, monkeypatch, origins: str) -> Settings:
        for key, value in {**self.ENV, "WORDLE_ALLOWED_ORIGINS": origins}.items():
            monkeypatch.setenv(key, value)
        return Settings(_env_file=None)

    def test_splits_a_comma_separated_list(self, monkeypatch):
        settings = self._settings(monkeypatch, "http://a.test,http://b.test")
        assert settings.allowed_origins == ["http://a.test", "http://b.test"]

    def test_trims_whitespace_around_entries(self, monkeypatch):
        settings = self._settings(monkeypatch, " http://a.test , http://b.test ")
        assert settings.allowed_origins == ["http://a.test", "http://b.test"]

    def test_accepts_a_single_origin(self, monkeypatch):
        assert self._settings(monkeypatch, "http://a.test").allowed_origins == ["http://a.test"]

    def test_drops_empty_entries(self, monkeypatch):
        assert self._settings(monkeypatch, "http://a.test,,").allowed_origins == ["http://a.test"]

    def test_still_accepts_a_list_in_code(self):
        settings = Settings(
            password="hunter2",
            secret_key="y" * 32,
            allowed_origins=["http://a.test"],
            _env_file=None,
        )
        assert settings.allowed_origins == ["http://a.test"]

    def test_reads_a_comma_separated_list_from_a_dotenv_file(self, tmp_path, monkeypatch):
        # The path that actually broke: .env parsing, not os.environ.
        env = tmp_path / ".env"
        env.write_text(
            "WORDLE_PASSWORD=hunter2\n"
            f"WORDLE_SECRET_KEY={'y' * 32}\n"
            "WORDLE_ALLOWED_ORIGINS=http://a.test,http://b.test\n",
            encoding="utf-8",
        )
        for key in ("WORDLE_PASSWORD", "WORDLE_SECRET_KEY", "WORDLE_ALLOWED_ORIGINS"):
            monkeypatch.delenv(key, raising=False)
        settings = Settings(_env_file=env)
        assert settings.allowed_origins == ["http://a.test", "http://b.test"]
