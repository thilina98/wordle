"""Settings must fail fast on a configuration that cannot work."""

import pytest

from wordle.app import create_app
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


def test_starts_with_no_secrets_at_all(no_secrets):
    # There is no shared password and no signing key any more.
    Settings(_env_file=None, _secrets_dir=no_secrets)


def test_reads_values_from_the_environment(monkeypatch):
    monkeypatch.setenv("WORDLE_WORD_LENGTH", "6")
    assert Settings(_env_file=None).word_length == 6


class TestAllowedOrigins:
    """CORS origins arrive as a comma-separated string from the environment."""

    def _settings(self, monkeypatch, origins: str) -> Settings:
        monkeypatch.setenv("WORDLE_ALLOWED_ORIGINS", origins)
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
            allowed_origins=["http://a.test"],
            _env_file=None,
        )
        assert settings.allowed_origins == ["http://a.test"]

    def test_reads_a_comma_separated_list_from_a_dotenv_file(self, tmp_path, monkeypatch):
        # The path that actually broke: .env parsing, not os.environ.
        env = tmp_path / ".env"
        env.write_text("WORDLE_ALLOWED_ORIGINS=http://a.test,http://b.test\n", encoding="utf-8")
        monkeypatch.delenv("WORDLE_ALLOWED_ORIGINS", raising=False)
        settings = Settings(_env_file=env)
        assert settings.allowed_origins == ["http://a.test", "http://b.test"]


class TestEveryLengthIsPlayable:
    """An installed length that could never yield a game stops startup."""

    def test_a_length_too_short_to_play_stops_startup(self, settings, tmp_path):
        from tests.conftest import write_length

        # A one-letter game would derive one attempt, below the floor of two.
        root = write_length(tmp_path / "tiny", 1, ["a", "i"], ["o"])
        with pytest.raises(ValueError, match="cannot be played"):
            create_app(settings.model_copy(update={"word_lists_dir": root}))

    def test_an_ordinary_length_starts(self, settings, tmp_path):
        from tests.conftest import write_length

        root = write_length(tmp_path / "multi", 4, ["cats", "dogs"], ["rats"])
        app = create_app(settings.model_copy(update={"word_lists_dir": root}))
        try:
            assert app.state.catalogue.lengths == (4,)
        finally:
            app.state.store.close()
