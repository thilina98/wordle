"""Settings, read from the environment.

Every value is overridable with a WORDLE_-prefixed environment variable, e.g.
WORDLE_AUTH_ISSUER. The one secret, the database password, is read from a file
in the secrets directory, never from .env.

Sign-in is off until an identity provider is configured. With it off, the game
is fully playable anonymously; nothing else changes.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Where secrets live, one file each. Secrets are never
# written down twice, so the same directory serves Docker and a run from
# source; only its location differs.
_SECRET_LOCATIONS = (
    Path("/run/secrets"),  # Docker mounts them here
    Path("secrets"),  # running from the repo root
    Path("../secrets"),  # running from backend/
)


def _secrets_dir() -> str | None:
    """First of the known locations that exists, or WORDLE_SECRETS_DIR.

    Resolved at import: the Docker mount is in place before the process
    starts, and pydantic-settings warns on every construction if handed a
    directory that is not there.
    """
    override = os.environ.get("WORDLE_SECRETS_DIR")
    candidates = (Path(override),) if override else _SECRET_LOCATIONS
    return next((str(c) for c in candidates if c.is_dir()), None)


class Settings(BaseSettings):
    # backend/.env, when run from backend/. In Docker, compose hands the same
    # file to the container as environment variables instead.
    model_config = SettingsConfigDict(
        env_prefix="WORDLE_",
        env_file=".env",
        env_file_encoding="utf-8",
        # One file per secret, named after the setting: wordle_database_password.
        # Kept out of .env and out of the environment -- `docker inspect`
        # prints the environment, not a file's contents.
        secrets_dir=_secrets_dir(),
        extra="ignore",
    )

    # --- Sign-in. Any standard OpenID Connect provider.
    auth_provider: Literal["oidc", "auth0"] = Field(
        default="oidc",
        description=(
            "oidc works with any OpenID Connect provider but cannot close "
            "accounts there. auth0 also closes the Auth0 account when a player "
            "deletes theirs."
        ),
    )
    auth_issuer: str | None = Field(
        default=None,
        description=(
            "Identity provider's issuer URL, exactly as its discovery document "
            "states it (Auth0's ends in a slash). Unset turns sign-in off."
        ),
    )
    auth_audience: str | None = Field(
        default=None,
        description="The identifier this API is registered under at the provider.",
    )
    auth_algorithms: Annotated[list[str], NoDecode] = Field(
        default=["RS256"],
        description="Accepted token signature algorithms. Comma-separated in the environment.",
    )
    auth_link_verified_emails: bool = Field(
        default=True,
        description=(
            "Join a new sign-in method to an existing player when the provider "
            "has verified they share an email."
        ),
    )

    # --- Auth0 only: the Machine to Machine application that closes accounts.
    auth0_client_id: str | None = Field(default=None)
    auth0_client_secret: str | None = Field(
        default=None,
        description="A secret file (wordle_auth0_client_secret), never an environment variable.",
    )

    # --- PostgreSQL: players, and everything else except games in progress.
    # Only connected to when sign-in is on.
    database_url: str | None = Field(
        default=None,
        description="PostgreSQL connection URL, without the password.",
    )
    database_password: str | None = Field(
        default=None,
        description="PostgreSQL password. A secret file, never an environment variable.",
    )

    # --- CORS. The frontend is a separate origin, so it must be named here.
    # NoDecode: without it pydantic-settings JSON-decodes the value straight
    # from the environment, and a comma-separated list never reaches the
    # validator below.
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:8080", "http://127.0.0.1:8080"],
        description="Frontend origins allowed to call the API. Comma-separated in the environment.",
    )

    # --- Game
    default_word_length: int | None = Field(
        default=None,
        ge=2,
        description=(
            "Length used when a game does not ask for one. None prefers 5, "
            "falling back to the shortest list installed."
        ),
    )
    # --- Active games: games being played, in their own SQLite file, apart
    # from the main database.
    active_games_store: Literal["memory", "sqlite"] = Field(
        default="sqlite",
        description="sqlite keeps games across a restart; memory loses them",
    )
    active_games_db_path: Path = Field(
        default=Path("data/games.db"),
        description="The SQLite file. Its folder is created if missing. Mount a volume there.",
    )
    active_games_max: int = Field(
        default=10_000,
        ge=1,
        description="Most games kept at once; the least recently played go first.",
    )
    active_games_ttl_seconds: int = Field(
        default=60 * 60 * 4,
        ge=60,
        description="A game untouched this long is dropped.",
    )

    word_lists_dir: Path | None = Field(
        default=None,
        description=(
            "Directory of word lists, one subdirectory per length "
            "(5/answers.csv, 5/dictionary.csv, ...). None uses the shipped lists."
        ),
    )

    @field_validator("allowed_origins", "auth_algorithms", mode="before")
    @classmethod
    def _split_list(cls, value: object) -> object:
        """Accept "a, b" from the environment as well as a list."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def sign_in_enabled(self) -> bool:
        return self.auth_issuer is not None

    @model_validator(mode="after")
    def _sign_in_is_complete(self) -> Settings:
        """Half a sign-in configuration is a mistake; stop at startup, not at login."""
        if not self.sign_in_enabled:
            return self
        if not self.auth_audience:
            raise ValueError("WORDLE_AUTH_AUDIENCE is required when WORDLE_AUTH_ISSUER is set")
        if not self.database_url:
            raise ValueError("WORDLE_DATABASE_URL is required when WORDLE_AUTH_ISSUER is set")
        if self.auth_provider == "auth0":
            if not self.auth0_client_id:
                raise ValueError(
                    "WORDLE_AUTH0_CLIENT_ID is required when WORDLE_AUTH_PROVIDER is auth0"
                )
            if not self.auth0_client_secret:
                raise ValueError(
                    "secrets/wordle_auth0_client_secret is required when "
                    "WORDLE_AUTH_PROVIDER is auth0"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is read once per process."""
    return Settings()  # type: ignore[call-arg]
