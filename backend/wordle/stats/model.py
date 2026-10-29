"""The values that cross the statistics seams, and the arithmetic on them.

Everything here is pure: no I/O, no clock. Both adapters fold results and
summarise rows through these functions, so they cannot disagree on what a
statistic means.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import StrEnum

from ..game import Difficulty, GameState
from ..scoring import FIRST_SCORABLE_ATTEMPT, Score, ScoringRules, score_game
from ..store import MIN_GUESSES_TO_ABANDON


class Outcome(StrEnum):
    WON = "won"
    LOST = "lost"
    #: Left unfinished after at least two guesses. Counts as a loss.
    ABANDONED = "abandoned"


class NotRecordable(ValueError):
    """The game cannot become a result: still being played, never timed, or left too early."""


@dataclass(frozen=True, slots=True)
class GameResult:
    """One game of a signed-in player, reduced to the facts statistics keep."""

    game_id: str
    player_id: str
    answer: str
    word_length: int
    max_attempts: int
    #: The label the game was played under. Frozen here, never recomputed.
    difficulty: Difficulty
    guesses: tuple[str, ...]
    outcome: Outcome
    attempt_won_on: int | None
    started_at: float
    ended_at: float

    @classmethod
    def of(
        cls, game_id: str, player_id: str, game: GameState, *, ended_at: float, abandoned: bool
    ) -> GameResult:
        """The result of a finished game, or of one abandoned mid-play.

        Raises NotRecordable for a game still being played, one left after a
        single guess, or one that was never timed (only games from before
        timing existed).
        """
        if game.is_over:
            outcome = Outcome.WON if game.is_won else Outcome.LOST
        elif abandoned:
            if len(game.attempts) < MIN_GUESSES_TO_ABANDON:
                raise NotRecordable("A game left after a single guess is not recorded")
            outcome = Outcome.ABANDONED
        else:
            raise NotRecordable("The game is still being played")
        if game.started_at is None:
            raise NotRecordable("The game was never timed")
        return cls(
            game_id=game_id,
            player_id=player_id,
            answer=game.target,
            word_length=game.word_length,
            max_attempts=game.max_attempts,
            difficulty=game.difficulty,
            guesses=tuple(a.guess for a in game.attempts),
            outcome=outcome,
            attempt_won_on=game.winning_attempt,
            started_at=game.started_at,
            # Never before the start, whatever clock the end was read from.
            ended_at=max(ended_at, game.started_at),
        )

    @property
    def won(self) -> bool:
        return self.outcome is Outcome.WON

    @property
    def scored_win(self) -> bool:
        """A win that earns points: attempt 2 or later. Attempt 1 is luck."""
        return self.won and self.attempt_won_on >= FIRST_SCORABLE_ATTEMPT

    @property
    def duration_ms(self) -> int:
        return round((self.ended_at - self.started_at) * 1000)

    def score(self, rules: ScoringRules) -> Score:
        """This game's score under `rules`. Losses and abandons score zero."""
        return score_game(
            rules,
            word_length=self.word_length,
            max_attempts=self.max_attempts,
            is_won=self.won,
            winning_attempt=self.attempt_won_on,
            game_time_seconds=self.ended_at - self.started_at,
        )


def as_points(score: Score) -> Decimal:
    """A score as stored: exact, so totals add up to the cent."""
    return Decimal(str(score.score))


@dataclass(frozen=True, slots=True)
class ComboStats:
    """One player's figures for one word length and difficulty. A summary row."""

    word_length: int
    difficulty: Difficulty
    games: int = 0
    wins: int = 0
    first_attempt_wins: int = 0
    last_attempt_wins: int = 0
    total_score: Decimal = Decimal(0)
    highest_score: Decimal = Decimal(0)
    #: Wins on attempt 2 or later only.
    total_win_ms: int = 0
    fastest_win_ms: int | None = None
    current_streak: int = 0
    best_streak: int = 0

    def after(self, result: GameResult, points: Decimal) -> ComboStats:
        """These figures with one more game added. The PostgreSQL upsert mirrors this."""
        win = result.won
        streak = self.current_streak + 1 if win else 0
        timed = result.duration_ms if result.scored_win else None
        fastest = self.fastest_win_ms
        if timed is not None:
            fastest = timed if fastest is None else min(fastest, timed)
        return replace(
            self,
            games=self.games + 1,
            wins=self.wins + win,
            first_attempt_wins=self.first_attempt_wins + (win and result.attempt_won_on == 1),
            last_attempt_wins=self.last_attempt_wins
            + (win and result.attempt_won_on == result.max_attempts),
            total_score=self.total_score + points,
            highest_score=max(self.highest_score, points),
            total_win_ms=self.total_win_ms + (timed or 0),
            fastest_win_ms=fastest,
            current_streak=streak,
            best_streak=max(self.best_streak, streak),
        )


@dataclass(frozen=True, slots=True)
class StatsSummary:
    """A player's statistics under one filter.

    Averages and percentages are None where they would divide by zero.
    Streaks are None unless the filter named both a word length and a
    difficulty: a streak belongs to one combination, and adding streaks from
    several means nothing.
    """

    games: int
    wins: int
    losses: int
    win_percentage: float | None
    first_attempt_wins: int
    last_attempt_wins: int
    total_score: float
    highest_score: float | None
    #: Over scored games only -- wins on attempt 2 or later. Losses and
    #: attempt-1 wins always score zero and are left out.
    average_score: float | None
    #: Wins on attempt 2 or later only.
    fastest_win_ms: int | None
    average_win_ms: int | None
    current_streak: int | None
    best_streak: int | None
    #: Wins by the attempt they were won on.
    guess_distribution: dict[int, int] = field(default_factory=dict)


def summarise(
    rows: list[ComboStats], guess_distribution: dict[int, int], *, one_combination: bool
) -> StatsSummary:
    """Add up the summary rows a filter selected."""
    games = sum(r.games for r in rows)
    wins = sum(r.wins for r in rows)
    first = sum(r.first_attempt_wins for r in rows)
    scored = wins - first
    total = sum((r.total_score for r in rows), Decimal(0))
    fastest = [r.fastest_win_ms for r in rows if r.fastest_win_ms is not None]
    # A combination with no games yet has no row, and a zero streak.
    row = rows[0] if rows else ComboStats(0, Difficulty.NORMAL)
    return StatsSummary(
        games=games,
        wins=wins,
        losses=games - wins,
        win_percentage=round(wins / games * 100, 2) if games else None,
        first_attempt_wins=first,
        last_attempt_wins=sum(r.last_attempt_wins for r in rows),
        total_score=float(total),
        highest_score=float(max(r.highest_score for r in rows)) if rows else None,
        average_score=round(float(total) / scored, 2) if scored else None,
        fastest_win_ms=min(fastest) if fastest else None,
        average_win_ms=round(sum(r.total_win_ms for r in rows) / scored) if scored else None,
        current_streak=row.current_streak if one_combination else None,
        best_streak=row.best_streak if one_combination else None,
        guess_distribution=dict(sorted(guess_distribution.items())),
    )
