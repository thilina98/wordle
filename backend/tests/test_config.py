"""Settings must fail fast on a configuration that cannot work."""

import pytest
from pydantic import ValidationError

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


def test_starts_with_no_secrets_at_all(monkeypatch, no_secrets):
    # Anonymous play needs nothing configured; there is no shared password.
    monkeypatch.delenv("WORDLE_AUTH_ISSUER", raising=False)
    settings = Settings(_env_file=None, _secrets_dir=no_secrets)
    assert settings.sign_in_enabled is False


def test_reads_values_from_the_environment(monkeypatch):
    monkeypatch.setenv("WORDLE_DEFAULT_WORD_LENGTH", "6")
    monkeypatch.setenv("WORDLE_AUTH_ISSUER", "https://id.example.test/")
    monkeypatch.setenv("WORDLE_AUTH_AUDIENCE", "https://wordle-api")
    monkeypatch.setenv("WORDLE_DATABASE_URL", "postgresql://wordle@db/wordle")
    settings = Settings(_env_file=None)
    assert settings.default_word_length == 6
    assert settings.sign_in_enabled is True


def test_reads_the_database_password_from_a_secret_file(tmp_path):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "wordle_database_password").write_text("s3cret", encoding="utf-8")
    settings = Settings(_env_file=None, _secrets_dir=str(secrets))
    assert settings.database_password == "s3cret"


class TestSignInConfiguration:
    """Half a sign-in configuration stops startup instead of failing at login."""

    ISSUER = "https://id.example.test/"

    def test_an_issuer_needs_an_audience(self, no_secrets):
        with pytest.raises(ValidationError, match="AUTH_AUDIENCE"):
            Settings(auth_issuer=self.ISSUER, _env_file=None, _secrets_dir=no_secrets)

    def test_sign_in_needs_a_database_url(self, no_secrets):
        with pytest.raises(ValidationError, match="DATABASE_URL"):
            Settings(
                auth_issuer=self.ISSUER,
                auth_audience="api",
                _env_file=None,
                _secrets_dir=no_secrets,
            )

    def test_auth0_needs_its_client_id_and_secret(self, no_secrets):
        base = dict(
            auth_issuer=self.ISSUER,
            auth_audience="api",
            database_url="postgresql://wordle@db/wordle",
            auth_provider="auth0",
            _env_file=None,
            _secrets_dir=no_secrets,
        )
        with pytest.raises(ValidationError, match="AUTH0_DELETION_APP_CLIENT_ID"):
            Settings(**base)
        with pytest.raises(ValidationError, match="wordle_auth0_deletion_app_client_secret"):
            Settings(**base, auth0_deletion_app_client_id="abc")
        assert Settings(
            **base, auth0_deletion_app_client_id="abc", auth0_deletion_app_client_secret="s3cret"
        )

    def test_the_auth0_secret_comes_from_its_secret_file(self, tmp_path):
        secrets = tmp_path / "secrets"
        secrets.mkdir()
        (secrets / "wordle_auth0_deletion_app_client_secret").write_text("s3cret", encoding="utf-8")
        assert (
            Settings(_env_file=None, _secrets_dir=str(secrets)).auth0_deletion_app_client_secret
            == "s3cret"
        )

    def test_the_app_builds_the_provider_that_is_named(self, settings, monkeypatch):
        from wordle.accounts import InMemoryPlayerRepository, postgres
        from wordle.accounts.auth0 import Auth0Provider
        from wordle.accounts.oidc import OidcProvider

        monkeypatch.setattr(
            postgres, "PostgresPlayerRepository", lambda *a, **k: InMemoryPlayerRepository()
        )
        common = {
            "auth_issuer": self.ISSUER,
            "auth_audience": "api",
            "database_url": "postgresql://wordle@db/wordle",
        }
        for update, expected in (
            ({"auth_provider": "oidc"}, OidcProvider),
            (
                {
                    "auth_provider": "auth0",
                    "auth0_deletion_app_client_id": "a",
                    "auth0_deletion_app_client_secret": "b",
                },
                Auth0Provider,
            ),
        ):
            app = create_app(settings.model_copy(update={**common, **update}))
            try:
                assert isinstance(app.state.accounts._provider, expected)
            finally:
                app.state.store.close()

    def test_algorithms_arrive_comma_separated(self, monkeypatch):
        monkeypatch.setenv("WORDLE_AUTH_ALGORITHMS", "RS256, ES256")
        assert Settings(_env_file=None).auth_algorithms == ["RS256", "ES256"]

    def test_the_app_builds_real_sign_in_from_settings(self, settings, monkeypatch):
        # No network: discovery is lazy. No database: the Postgres adapter is
        # swapped for the in-memory one, which takes no connection.
        from wordle.accounts import InMemoryPlayerRepository, postgres

        monkeypatch.setattr(
            postgres, "PostgresPlayerRepository", lambda *a, **k: InMemoryPlayerRepository()
        )
        configured = settings.model_copy(
            update={
                "auth_issuer": self.ISSUER,
                "auth_audience": "api",
                "database_url": "postgresql://wordle@db/wordle",
            }
        )
        app = create_app(configured)
        try:
            from wordle.accounts import Accounts

            assert isinstance(app.state.accounts, Accounts)
        finally:
            app.state.store.close()


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
