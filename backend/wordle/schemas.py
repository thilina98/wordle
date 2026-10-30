"""API request and response shapes. One view model serves every game endpoint."""

from __future__ import annotations

from dataclasses import asdict

from pydantic import BaseModel, Field

from .accounts import Player
from .game import MIN_ATTEMPTS, Colour, GameState
from .scoring import Score, ScoringRules, score_for
from .stats import StatsSummary


class PlayerView(BaseModel):
    """A signed-in player, as they see themselves."""

    player_id: str
    display_name: str

    @classmethod
    def of(cls, player: Player) -> PlayerView:
        return cls(player_id=player.player_id, display_name=player.display_name)


class CreateGameRequest(BaseModel):
    """Options for a new game. Every field optional, so an empty body works."""

    word_length: int | None = Field(
        default=None, ge=2, le=32, description="None takes the server's default length."
    )
    max_attempts: int | None = Field(
        default=None,
        ge=MIN_ATTEMPTS,
        description=(
            "None derives it from the word length. The upper bound depends on "
            "that length, so the game enforces it, not this schema."
        ),
    )


class GuessRequest(BaseModel):
    # Length and character rules live in the domain, so the error text is
    # identical wherever a guess arrives from. The cap here just bounds input.
    guess: str = Field(max_length=64)


class AttemptView(BaseModel):
    guess: str
    colours: list[Colour]


class ScoreView(BaseModel):
    """A finished game's score, with the working shown.

    Every term the formula produced is here, not just the total, so the client
    can explain a score without reimplementing the arithmetic.
    """

    word_length: int
    max_attempts: int
    is_won: bool
    winning_attempt: int | None
    game_time_seconds: float
    base: float
    time_bonus: float
    multiplier: float
    raw_score: float
    score: float

    @classmethod
    def of(cls, score: Score) -> ScoreView:
        return cls(**asdict(score))


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
    #: Null until the game is over. There is no score for a game in progress.
    score: ScoreView | None = None
    #: Whether the game belongs to the player asking. An owned game counts in
    #: their statistics. Always false for an anonymous player; false for a
    #: signed-in one only when they started it signed out and guessed in it
    #: before signing in.
    owned: bool = False

    @classmethod
    def of(cls, game_id: str, game: GameState, rules: ScoringRules, *, owned: bool) -> GameView:
        score = score_for(game, rules)
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
            score=ScoreView.of(score) if score else None,
            owned=owned,
        )


class StatsView(BaseModel):
    """A player's statistics under the filter they asked for.

    Null where a figure would divide by zero. Streaks are null unless both a
    word length and a difficulty were asked for. Times are in milliseconds and
    count wins on attempt 2 or later only; so does `average_score`, which
    leaves out losses and attempt-1 wins because they always score zero.
    """

    games: int
    wins: int
    losses: int
    win_percentage: float | None
    first_attempt_wins: int
    last_attempt_wins: int
    total_score: float
    highest_score: float | None
    average_score: float | None
    fastest_win_ms: int | None
    average_win_ms: int | None
    current_streak: int | None
    best_streak: int | None
    #: Wins by the attempt they were won on.
    guess_distribution: dict[int, int]

    @classmethod
    def of(cls, summary: StatsSummary) -> StatsView:
        return cls(**asdict(summary))
