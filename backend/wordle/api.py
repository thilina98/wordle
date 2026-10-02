"""The whole HTTP surface. This service serves JSON only: the frontend is a
separate application on its own origin and fetches everything from here."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from .config import Settings
from .game import GameOverError, GameState, InvalidGuessError
from .schemas import CreateGameRequest, GameView, GuessRequest, LoginRequest, TokenResponse
from .security import (
    LoginThrottle,
    TokenError,
    bearer_token,
    issue_token,
    verify_password,
    verify_token,
)
from .store import GameStore
from .words import WordCatalogue

router = APIRouter(prefix="/api", tags=["wordle"])


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _store(request: Request) -> GameStore:
    return request.app.state.store


def _catalogue(request: Request) -> WordCatalogue:
    return request.app.state.catalogue


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
def create_game(
    request: Request,
    payload: CreateGameRequest | None = None,
) -> GameView:
    """Start a game with a random answer, at the requested shape.

    The body is optional, and so is every field in it: anything left out falls
    back to the server's default.
    """
    catalogue = _catalogue(request)
    length = payload.word_length if payload else None
    if length is not None and length not in catalogue:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"No {length}-letter words available. Try: {catalogue.describe_lengths()}",
        )
    # `is None`, not `or`: a falsy count must still be the domain's to refuse,
    # not silently replaced by the default. None all the way down means the
    # game derives the count from its own word length.
    requested = payload.max_attempts if payload else None
    attempts = _settings(request).max_attempts if requested is None else requested

    try:
        game = GameState(
            target=catalogue.answers(length).random_word(),
            vocabulary=catalogue.dictionary(length).vocabulary,
            max_attempts=attempts,
        )
    except ValueError as exc:
        # The schema bounds the same field, so this is belt and braces. It
        # exists because the domain's limits are the real ones: the route
        # should answer for them rather than assume the edge caught everything.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
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
        # Rejected guesses cost the player nothing, so nothing is saved.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    _store(request).save(game_id, game)
    return GameView.of(game_id, game)
