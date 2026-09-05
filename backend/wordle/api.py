"""The whole HTTP surface. This service serves JSON only: the frontend is a
separate application on its own origin and fetches everything from here."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from .game import GameOverError, GameState, InvalidGuessError
from .schemas import GameView, GuessRequest, LoginRequest, TokenResponse
from .security import (
    LoginThrottle,
    TokenError,
    bearer_token,
    issue_token,
    verify_password,
    verify_token,
)
from .store import GameStore
from .words import WordRepository

router = APIRouter(prefix="/api", tags=["wordle"])


def _settings(request: Request):
    return request.app.state.settings


def _store(request: Request) -> GameStore:
    return request.app.state.store


def _repository(request: Request) -> WordRepository:
    return request.app.state.repository


def _client_id(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def require_token(request: Request, authorization: str | None = Header(default=None)) -> None:
    """Gate for every game route. 401 with no detail about why beyond the basics."""
    settings = _settings(request)
    try:
        verify_token(bearer_token(authorization), settings.secret_key, settings.token_max_age)
    except TokenError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _load_game(request: Request, game_id: str) -> GameState:
    game = _store(request).get(game_id)
    if game is None:
        # Expired and never-existed look the same on purpose.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Game not found")
    return game


# --- Access ---------------------------------------------------------------


@router.post("/login", response_model=TokenResponse)
def login(request: Request, payload: LoginRequest) -> TokenResponse:
    """Exchange the shared password for a signed token.

    The only unauthenticated route besides the health check.
    """
    settings = _settings(request)
    throttle: LoginThrottle = request.app.state.throttle
    client = _client_id(request)

    if throttle.is_locked(client):
        wait = int(throttle.retry_after(client)) + 1
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many attempts. Try again in {wait} seconds.",
            headers={"Retry-After": str(wait)},
        )

    if not verify_password(payload.password, settings.password):
        throttle.record_failure(client)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong password")

    throttle.record_success(client)
    return TokenResponse(token=issue_token(settings.secret_key), expires_in=settings.token_max_age)


@router.get("/session", dependencies=[Depends(require_token)])
def check_session() -> dict[str, bool]:
    """Cheap way for the frontend to ask whether its stored token still works."""
    return {"valid": True}


# --- Game -----------------------------------------------------------------


@router.post(
    "/games",
    response_model=GameView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_token)],
)
def create_game(request: Request) -> GameView:
    """Start a game with a random answer."""
    repository = _repository(request)
    game = GameState(
        target=repository.random_word(),
        vocabulary=repository.vocabulary,
        max_attempts=_settings(request).max_attempts,
    )
    return GameView.of(_store(request).create(game), game)


@router.get("/games/{game_id}", response_model=GameView, dependencies=[Depends(require_token)])
def read_game(request: Request, game_id: str) -> GameView:
    """Current board, for resuming after a reload."""
    return GameView.of(game_id, _load_game(request, game_id))


@router.post(
    "/games/{game_id}/guesses", response_model=GameView, dependencies=[Depends(require_token)]
)
def submit_guess(request: Request, game_id: str, payload: GuessRequest) -> GameView:
    """Score one guess and return the updated board."""
    game = _load_game(request, game_id)
    try:
        game.guess(payload.guess)
    except GameOverError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except InvalidGuessError as exc:
        # Rejected guesses cost the player nothing.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return GameView.of(game_id, game)
