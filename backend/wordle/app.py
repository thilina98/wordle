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
from .game import MIN_ATTEMPTS, default_attempts
from .store import GameStore, InMemoryGameStore, SqliteGameStore
from .words import WordCatalogue, WordListError


def _catalogue(settings: Settings) -> WordCatalogue:
    """Every word length this deployment can serve.

    The shipped lists are five-letter. Serving another length means installing
    a directory for it and pointing WORDLE_WORD_LISTS_DIR at the root.
    """
    try:
        if settings.word_lists_dir:
            return WordCatalogue.from_directory(
                settings.word_lists_dir, default_length=settings.word_length
            )
        return WordCatalogue.packaged(default_length=settings.word_length)
    except WordListError as exc:
        if settings.word_length is not None and not settings.word_lists_dir:
            raise WordListError(
                f"WORDLE_WORD_LENGTH={settings.word_length} is not among the shipped "
                f"word lists. Point WORDLE_WORD_LISTS_DIR at a directory holding a "
                f"{settings.word_length}/ list, or leave WORDLE_WORD_LENGTH unset. ({exc})"
            ) from exc
        raise


def _check_every_length_is_playable(catalogue: WordCatalogue) -> None:
    """A length whose derived count is below the floor can never be played.

    Caught here so the mistake stops the server, rather than failing every
    game of that length one request at a time.
    """
    for length in catalogue.lengths:
        if default_attempts(length) < MIN_ATTEMPTS:
            raise ValueError(
                f"The installed {length}-letter list cannot be played: it derives "
                f"{default_attempts(length)} attempts and a game needs at least "
                f"{MIN_ATTEMPTS}. Remove the {length}/ directory."
            )


def _game_store(settings: Settings, catalogue: WordCatalogue) -> GameStore:
    """Games on disk by default, so a container rebuild does not end them."""
    if settings.store == "memory":
        return InMemoryGameStore(
            ttl_seconds=settings.game_ttl_seconds, max_games=settings.max_games
        )
    return SqliteGameStore(
        settings.data_dir / "games.db",
        vocabulary_for=catalogue.vocabulary_for,
        ttl_seconds=settings.game_ttl_seconds,
        max_games=settings.max_games,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    catalogue = _catalogue(settings)
    _check_every_length_is_playable(catalogue)

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
    app.state.catalogue = catalogue
    app.state.store = _game_store(settings, catalogue)

    # Named origins only. Nothing travels in a cookie, so credentialed CORS is
    # not needed, and "*" would be a needless invitation.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    app.include_router(api_router)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        """Unauthenticated liveness probe. Reveals nothing about the game."""
        return {"status": "ok"}

    return app
