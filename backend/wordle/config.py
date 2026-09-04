"""Settings, read from the environment.

Every value is overridable with a WORDLE_-prefixed environment variable, e.g.
WORDLE_PASSWORD. Secrets have no defaults: the app refuses to start without them
rather than falling back to something guessable.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .game import MAX_ATTEMPTS, WORD_LENGTH


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WORDLE_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Secrets. No defaults on purpose.
    password: str = Field(min_length=1, description="Shared password for site access")
    secret_key: str = Field(min_length=16, description="Key signing the session cookie")

    # --- Session cookie
    session_max_age: int = Field(default=60 * 60 * 12, ge=60)
    cookie_secure: bool = Field(
        default=False,
        description="Require HTTPS for the cookie. Leave false when serving over plain HTTP.",
    )

    # --- Game
    word_length: int = Field(default=WORD_LENGTH, ge=2)
    max_attempts: int = Field(default=MAX_ATTEMPTS, ge=1)
    word_list_path: Path | None = Field(default=None, description="Override the shipped CSV")

    # --- Limits
    game_ttl_seconds: int = Field(default=60 * 60 * 4, ge=60)
    max_games: int = Field(default=10_000, ge=1)
    login_max_failures: int = Field(default=10, ge=1)
    login_lockout_seconds: int = Field(default=300, ge=1)

    # --- Frontend
    frontend_dir: Path = Field(default=Path(__file__).resolve().parents[2] / "frontend")


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is read once per process."""
    return Settings()  # type: ignore[call-arg]
