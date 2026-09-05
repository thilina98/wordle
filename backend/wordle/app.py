"""Application factory.

This service is the API and nothing else. It serves no HTML, no CSS and no
JavaScript; the frontend is a separate application, deployed and run on its
own. The two talk over the routes in api.py and share nothing else.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router as api_router
from .config import Settings, get_settings
from .security import LoginThrottle
from .store import InMemoryGameStore
from .words import WordRepository


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    repository = (
        WordRepository(settings.word_list_path, word_length=settings.word_length)
        if settings.word_list_path
        else WordRepository.default(word_length=settings.word_length)
    )

    app = FastAPI(
        title="Wordle API",
        version="2.0.0",
        # The schema maps the protected routes; keep it off the public internet.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.repository = repository
    app.state.store = InMemoryGameStore(
        ttl_seconds=settings.game_ttl_seconds, max_games=settings.max_games
    )
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
