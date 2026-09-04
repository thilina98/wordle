"""Application factory: session gate, game API, and the static frontend.

Nothing is served without a valid session except the login page and the health
check. That includes the HTML, the CSS and the JavaScript, so the site as a
whole sits behind the password rather than just its API.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from .api import router as api_router
from .config import Settings, get_settings
from .security import SESSION_KEY, LoginThrottle, verify_password
from .store import InMemoryGameStore
from .words import WordRepository

ERROR_PLACEHOLDER = "<!--ERROR-->"


def _is_authenticated(request: Request) -> bool:
    return bool(request.session.get(SESSION_KEY))


def require_session(request: Request) -> None:
    """Gate for JSON routes: no redirect, just 401."""
    if not _is_authenticated(request):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")


def _client_id(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@lru_cache(maxsize=8)
def _read_page(path: Path) -> str:
    """Pages are read once per process; uvicorn --reload picks up edits."""
    return path.read_text(encoding="utf-8")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    repository = (
        WordRepository(settings.word_list_path, word_length=settings.word_length)
        if settings.word_list_path
        else WordRepository.default(word_length=settings.word_length)
    )

    app = FastAPI(
        title="Wordle",
        version="1.0.0",
        # The schema describes protected routes; keep it off the public internet.
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

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        max_age=settings.session_max_age,
        same_site="lax",
        https_only=settings.cookie_secure,
    )

    app.include_router(api_router, dependencies=[Depends(require_session)])

    frontend = settings.frontend_dir.resolve()

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        """Unauthenticated liveness probe. Reveals nothing about the game."""
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index(request: Request) -> Response:
        if not _is_authenticated(request):
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        return HTMLResponse(_read_page(frontend / "index.html"))

    @app.get("/login", response_class=HTMLResponse, include_in_schema=False)
    def login_page(request: Request) -> Response:
        if _is_authenticated(request):
            return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
        return HTMLResponse(_login_html())

    @app.post("/login", include_in_schema=False)
    def login(request: Request, password: str = Form(default="")) -> Response:
        throttle: LoginThrottle = app.state.throttle
        client = _client_id(request)

        if throttle.is_locked(client):
            wait = int(throttle.retry_after(client)) + 1
            return HTMLResponse(
                _login_html(f"Too many attempts. Try again in {wait} seconds."),
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(wait)},
            )

        if not verify_password(password, settings.password):
            throttle.record_failure(client)
            return HTMLResponse(
                _login_html("Wrong password."), status_code=status.HTTP_401_UNAUTHORIZED
            )

        throttle.record_success(client)
        # Fresh session id on login, so a pre-set cookie cannot be reused.
        request.session.clear()
        request.session[SESSION_KEY] = True
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/logout", include_in_schema=False)
    def logout(request: Request) -> Response:
        request.session.clear()
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/static/{asset:path}", include_in_schema=False)
    def static_asset(request: Request, asset: str) -> Response:
        # Guarded by hand rather than mounted, so assets need a session too.
        require_session(request)
        target = (frontend / asset).resolve()
        if not target.is_relative_to(frontend) or not target.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        return FileResponse(target)

    def _login_html(error: str | None = None) -> str:
        page = _read_page(frontend / "login.html")
        banner = f'<p class="error" role="alert">{error}</p>' if error else ""
        return page.replace(ERROR_PLACEHOLDER, banner)

    return app
