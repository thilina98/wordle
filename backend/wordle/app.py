"""Application factory.

This service is the API and nothing else. It serves no HTML, no CSS and no
JavaScript; the frontend is a separate application, deployed and run on its
own. The two talk over the routes in api.py and share nothing else.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router as api_router
from .config import Settings, get_settings
from .security import LoginThrottle
from .store import GameStore, InMemoryGameStore, SqliteGameStore
from .words import WordRepository


def _word_lists(settings: Settings) -> tuple[WordRepository, WordRepository]:
    """Answers and allowed guesses, either overridden or the shipped pair."""
    if settings.answers_path or settings.dictionary_path:
        # Overriding one and not the other is almost always a mistake, so a
        # missing path falls back to the same file rather than the shipped one.
        answers_path = settings.answers_path or settings.dictionary_path
        dictionary_path = settings.dictionary_path or settings.answers_path
        return (
            WordRepository(answers_path, word_length=settings.word_length),
            WordRepository(dictionary_path, word_length=settings.word_length),
        )
    return WordRepository.default_pair(word_length=settings.word_length)


def _game_store(settings: Settings, dictionary: WordRepository) -> GameStore:
    """Games on disk by default, so a container rebuild does not end them."""
    if settings.store == "memory":
        return InMemoryGameStore(
            ttl_seconds=settings.game_ttl_seconds, max_games=settings.max_games
        )
    return SqliteGameStore(
        settings.data_dir / "games.db",
        vocabulary=dictionary.vocabulary,
        ttl_seconds=settings.game_ttl_seconds,
        max_games=settings.max_games,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    answers, dictionary = _word_lists(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        # Release the database connection on a clean shutdown.
        with suppress(AttributeError):
            app.state.store.close()

    app = FastAPI(
        lifespan=lifespan,
        title="Wordle API",
        version="2.0.0",
        # The schema maps the protected routes; keep it off the public internet.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.answers = answers
    app.state.dictionary = dictionary
    app.state.store = _game_store(settings, dictionary)
    app.state.throttle = LoginThrottle(
        max_failures=settings.login_max_failures,
        lockout_seconds=settings.login_lockout_seconds,
    )

    # Named origins only. The token travels in a header, not a cookie, so
    # credentialed CORS is not needed and "*" would be a needless invitation.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(api_router)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        """Unauthenticated liveness probe. Reveals nothing about the game."""
        return {"status": "ok"}

    return app
