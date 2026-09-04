"""API request and response shapes. One view model serves every game endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .game import Colour, GameState


class GuessRequest(BaseModel):
    # Length and character rules live in the domain, so the error text is
    # identical wherever a guess arrives from. The cap here just bounds input.
    guess: str = Field(max_length=64)


class AttemptView(BaseModel):
    guess: str
    colours: list[Colour]


class GameView(BaseModel):
    """Everything the client needs to draw the board.

    `answer` stays null until the game is over, so the page can never leak it.
    """

    game_id: str
    word_length: int
    max_attempts: int
    attempts: list[AttemptView]
    attempts_remaining: int
    is_over: bool
    is_won: bool
    letter_states: dict[str, Colour]
    answer: str | None = None

    @classmethod
    def of(cls, game_id: str, game: GameState) -> GameView:
        return cls(
            game_id=game_id,
            word_length=game.word_length,
            max_attempts=game.max_attempts,
            attempts=[AttemptView(guess=a.guess, colours=a.colours) for a in game.attempts],
            attempts_remaining=game.attempts_remaining,
            is_over=game.is_over,
            is_won=game.is_won,
            letter_states=game.letter_states,
            answer=game.target if game.is_over else None,
        )
