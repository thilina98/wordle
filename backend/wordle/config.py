"""Settings, read from the environment.

Every value is overridable with a WORDLE_-prefixed environment variable, e.g.
WORDLE_PASSWORD. Secrets have no defaults: the app refuses to start without them
rather than falling back to something guessable.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from .game import MAX_ATTEMPTS, WORD_LENGTH


class Settings(BaseSettings):
    # Two candidate .env files so one file at the repo root serves both Docker
    # and a local run from backend/. A backend/.env, if present, wins.
    model_config = SettingsConfigDict(
        env_prefix="WORDLE_",
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Secrets. No defaults on purpose.
    password: str = Field(min_length=1, description="Shared password for API access")
    secret_key: str = Field(min_length=16, description="Key signing the access token")

    # --- Access token
    token_max_age: int = Field(default=60 * 60 * 12, ge=60, description="Token lifetime, seconds")

    # --- CORS. The frontend is a separate origin, so it must be named here.
    # NoDecode: without it pydantic-settings JSON-decodes the value straight
    # from the environment, and a comma-separated list never reaches the
    # validator below.
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:8080", "http://127.0.0.1:8080"],
        description="Frontend origins allowed to call the API. Comma-separated in the environment.",
    )

    # --- Game
    word_length: int = Field(default=WORD_LENGTH, ge=2)
    max_attempts: int = Field(default=MAX_ATTEMPTS, ge=1)
    answers_path: Path | None = Field(default=None, description="Override the shipped answer list")
    dictionary_path: Path | None = Field(
        default=None, description="Override the shipped list of allowed guesses"
    )

    # --- Limits
    game_ttl_seconds: int = Field(default=60 * 60 * 4, ge=60)
    max_games: int = Field(default=10_000, ge=1)
    login_max_failures: int = Field(default=10, ge=1)
    login_lockout_seconds: int = Field(default=300, ge=1)

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept "http://a, http://b" from the environment as well as a list."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is read once per process."""
    return Settings()  # type: ignore[call-arg]
