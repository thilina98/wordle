"""The whole HTTP surface. This service serves JSON only: the frontend is a
separate application on its own origin and fetches everything from here.

Every game route works without signing in. A request carrying a valid token
plays as that player: games it starts belong to the player and nobody else can
open them. A request carrying a bad token is refused, never treated as anonymous.
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from .accounts import AccountsUnavailable, AuthenticationError, Player
from .game import GameOverError, GameState, InvalidGuessError
from .schemas import CreateGameRequest, GameView, GuessRequest, PlayerView
from .store import GameStore
from .words import WordCatalogue

router = APIRouter(prefix="/api", tags=["wordle"])


def _store(request: Request) -> GameStore:
    return request.app.state.store


def _catalogue(request: Request) -> WordCatalogue:
    return request.app.state.catalogue


def current_player(
    request: Request, authorization: str | None = Header(default=None)
) -> Player | None:
    """The signed-in player, or None for an anonymous one."""
    try:
        return request.app.state.accounts.identify(authorization)
    except AuthenticationError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except AccountsUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Sign-in is unavailable. Try again shortly."
        ) from exc


#: The signed-in player, or None for an anonymous one.
MaybePlayer = Annotated[Player | None, Depends(current_player)]


def require_player(player: MaybePlayer) -> Player:
    """For routes that only make sense signed in."""
    if player is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Sign in to do this",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return player


SignedInPlayer = Annotated[Player, Depends(require_player)]


def _viewer(player: Player | None) -> str | None:
    return player.player_id if player else None


def _now() -> float:
    """The clock every timed route reads.

    Wall clock, not monotonic, because a game outlives the process: its start
    is written to a row that a restarted server has to be able to subtract
    from. The server keeps time, not the client, so a doctored page cannot
    claim a four-second game.
    """
    return time.time()


def _load_game(request: Request, game_id: str, player: Player | None) -> GameState:
    game = _store(request).get(game_id, viewer=_viewer(player))
    if game is None:
        # Expired, never-existed and someone else's look the same on purpose.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Game not found")
    return game


# --- Accounts -------------------------------------------------------------


@router.get("/players/me", response_model=PlayerView)
def read_my_player(player: SignedInPlayer) -> PlayerView:
    """Who the token belongs to.

    There is no separate sign-up: the first call with a new identity creates
    the player (or joins it to one with the same verified email), so a client
    calls this once after signing in at the identity provider.
    """
    return PlayerView.of(player)


@router.delete("/players/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_player(request: Request, player: SignedInPlayer) -> None:
    """Delete the signed-in player: their account here and their games.

    The account at the identity provider is not touched. A client should sign
    the player out straight after: the same token, used again, signs in as a
    brand-new player.
    """
    try:
        request.app.state.accounts.delete(player)
    except AccountsUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Could not delete the account. Try again shortly."
        ) from exc
    # After the player, so a database outage leaves everything as it was.
    # Games left over by a failure here are unreachable and expire anyway.
    _store(request).delete_owned_by(player.player_id)


# --- Game -----------------------------------------------------------------


@router.post(
    "/games",
    response_model=GameView,
    status_code=status.HTTP_201_CREATED,
)
def create_game(
    request: Request,
    player: MaybePlayer,
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
    # None all the way down: the game derives the count from its own word.
    try:
        game = GameState(
            target=catalogue.answers(length).random_word(),
            vocabulary=catalogue.dictionary(length).vocabulary,
            max_attempts=payload.max_attempts if payload else None,
        )
    except ValueError as exc:
        # The schema bounds the same field, so this is belt and braces. It
        # exists because the domain's limits are the real ones: the route
        # should answer for them rather than assume the edge caught everything.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return GameView.of(_store(request).create(game, owner=_viewer(player)), game)


@router.get("/games/{game_id}", response_model=GameView)
def read_game(request: Request, game_id: str, player: MaybePlayer) -> GameView:
    """Current board, for resuming after a reload."""
    return GameView.of(game_id, _load_game(request, game_id, player))


@router.post("/games/{game_id}/start", response_model=GameView)
def start_game(request: Request, game_id: str, player: MaybePlayer) -> GameView:
    """Start this game's clock, on the player's first keystroke.

    Separate from creating the game because the two are not the same moment: a
    board can sit untouched while its player reads the rules, and that is not
    time spent playing. Idempotent, so the client may call it on every
    keystroke and only the first one counts.
    """
    game = _load_game(request, game_id, player)
    game.start_timer(_now())
    _store(request).save(game_id, game)
    return GameView.of(game_id, game)


@router.post("/games/{game_id}/guesses", response_model=GameView)
def submit_guess(
    request: Request,
    game_id: str,
    payload: GuessRequest,
    player: MaybePlayer,
) -> GameView:
    """Score one guess and return the updated board."""
    game = _load_game(request, game_id, player)
    try:
        game.guess(payload.guess, now=_now())
    except GameOverError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except InvalidGuessError as exc:
        # Rejected guesses cost the player nothing, so nothing is saved.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    _store(request).save(game_id, game)
    return GameView.of(game_id, game)
