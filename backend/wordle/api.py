"""Game endpoints. Every route here requires an authenticated session."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from .game import GameOverError, GameState, InvalidGuessError
from .schemas import GameView, GuessRequest
from .store import GameStore
from .words import WordRepository

router = APIRouter(prefix="/api", tags=["game"])


def _store(request: Request) -> GameStore:
    return request.app.state.store


def _repository(request: Request) -> WordRepository:
    return request.app.state.repository


def _load_game(request: Request, game_id: str) -> GameState:
    game = _store(request).get(game_id)
    if game is None:
        # Expired and never-existed look the same on purpose.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Game not found")
    return game


@router.post("/games", response_model=GameView, status_code=status.HTTP_201_CREATED)
def create_game(request: Request) -> GameView:
    """Start a game with a random answer."""
    repository = _repository(request)
    game = GameState(
        target=repository.random_word(),
        vocabulary=repository.vocabulary,
        max_attempts=request.app.state.settings.max_attempts,
    )
    return GameView.of(_store(request).create(game), game)


@router.get("/games/{game_id}", response_model=GameView)
def read_game(request: Request, game_id: str) -> GameView:
    """Current board, for resuming after a reload."""
    return GameView.of(game_id, _load_game(request, game_id))


@router.post("/games/{game_id}/guesses", response_model=GameView)
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
