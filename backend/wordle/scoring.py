"""How a finished game turns into points. Pure arithmetic: no I/O, no clock.

The whole system is one function. Callers hand over the facts of a finished
game and get back every intermediate term, because a score nobody can explain
is a score nobody trusts: the UI can show the working, and a stored row can be
recomputed and checked.

The formula lives here; its numbers do not. They arrive as `ScoringRules`,
read from the active scoring version in the database, or from WORDLE_SCORING_*
settings when the server runs without one. Changing the numbers is then a
data change, not a release.
"""

from __future__ import annotations

from dataclasses import dataclass

from .game import MIN_ATTEMPTS, GameState

#: The first attempt that can earn anything. Attempt 1 has no feedback behind
#: it, so winning on it is luck, not play -- the same fact that sets the floor
#: on how short a game may be, which is why this is MIN_ATTEMPTS and not a
#: second 2 written down somewhere else. A game rule, so not a scoring setting.
FIRST_SCORABLE_ATTEMPT = MIN_ATTEMPTS


@dataclass(frozen=True, slots=True)
class ScoringRules:
    """Every number that shapes a score, and the version they were released as.

    `version` is None for rules taken from settings: those scores are shown,
    never stored, so they need no version.
    """

    #: Points for the best possible win: attempt 2, before any time bonus.
    max_base: float
    #: What a win on attempt number word_length keeps, as a fraction of
    #: max_base. The decay between attempt 2 and that attempt follows from
    #: this and nothing else.
    last_attempt_ratio: float
    #: The most the time bonus can add, as a fraction of base. Small on
    #: purpose: solving it in fewer guesses must always beat solving it faster.
    time_bonus_cap: float
    #: The time window a player is given, per letter of the answer. Longer
    #: words get proportionally longer, so a pace scores the same whatever the
    #: length.
    seconds_per_letter: float
    #: Normal mode is one attempt per letter. Each attempt fewer than that
    #: multiplies the score by this; each attempt more divides by it.
    difficulty_step: float
    #: The most a game in normal mode can score. Fewer attempts than normal is
    #: a harder game, and scores more.
    normal_max_score: float
    #: Decimal places the final score is reported to. Every step before it
    #: keeps full precision.
    score_precision: int
    version: int | None = None

    @property
    def normal_max_raw_score(self) -> float:
        """The best normal-mode game in raw points: a win on attempt 2 in no time
        at all. The same whatever the word length, which is what makes scores
        comparable across lengths."""
        return self.max_base * (1 + self.time_bonus_cap)


@dataclass(frozen=True, slots=True)
class Score:
    """A finished game's score and the whole of its working.

    `score` is the only number meant for a player. The rest is kept so the
    result can be explained, audited, or recomputed after a rule change.
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


def score_game(
    rules: ScoringRules,
    *,
    word_length: int,
    max_attempts: int,
    is_won: bool,
    winning_attempt: int | None,
    game_time_seconds: float,
) -> Score:
    """Score one finished game.

    `max_attempts` is the allowance this game was played with. It affects the
    difficulty multiplier and nothing else: how hard the win was is measured
    against the word's length, not against the help the player was given, so
    the same performance on the same word is worth the same base either way.

    A loss scores zero, and so does a win on attempt 1 -- it still counts as a
    win everywhere else, it just earns nothing.

    Scores are not capped. `rules.normal_max_score` is the most a normal-mode
    game can score; playing with fewer attempts is harder and is meant to be
    worth more, playing with more is worth less.
    """
    if not is_won or winning_attempt is None or winning_attempt < FIRST_SCORABLE_ATTEMPT:
        return Score(
            word_length=word_length,
            max_attempts=max_attempts,
            is_won=is_won,
            winning_attempt=winning_attempt if is_won else None,
            game_time_seconds=game_time_seconds,
            base=0.0,
            time_bonus=0.0,
            multiplier=0.0,
            raw_score=0.0,
            score=0.0,
        )

    # Fewer attempts, more points. `progress` runs 0 at the first scorable
    # attempt to 1 at attempt number word_length, and past 1 when a generous
    # allowance let the player go further -- which keeps decaying, as it should.
    span = word_length - FIRST_SCORABLE_ATTEMPT
    if span <= 0:
        # A word so short that its first scorable attempt is also its last: the
        # curve has no room to run. Every win is a last-attempt win.
        progress = 1.0
    else:
        progress = (winning_attempt - FIRST_SCORABLE_ATTEMPT) / span
    base = rules.max_base * rules.last_attempt_ratio**progress

    # The window depends on the word alone. A player handed extra attempts is
    # not also handed extra time.
    window_seconds = rules.seconds_per_letter * word_length
    unused_time_fraction = max(0.0, 1 - game_time_seconds / window_seconds)
    time_bonus = base * rules.time_bonus_cap * unused_time_fraction

    # Normal mode is one attempt per letter; this prices the distance from it.
    multiplier = rules.difficulty_step ** (word_length - max_attempts)

    raw_score = (base + time_bonus) * multiplier
    return Score(
        word_length=word_length,
        max_attempts=max_attempts,
        is_won=True,
        winning_attempt=winning_attempt,
        game_time_seconds=game_time_seconds,
        base=base,
        time_bonus=time_bonus,
        multiplier=multiplier,
        raw_score=raw_score,
        # Rounded once, at the end. Rounding anything earlier would let two
        # genuinely different games tie.
        score=round(
            raw_score / rules.normal_max_raw_score * rules.normal_max_score,
            rules.score_precision,
        ),
    )


def score_for(game: GameState, rules: ScoringRules) -> Score | None:
    """Score a finished game, or None while it is still being played.

    The single place that knows how a GameState's facts line up with the
    scoring inputs, so no caller has to work out that the winning attempt is
    the number of attempts taken, or which of the two attempt counts on a game
    is the one that was actually played with.

    A finished game that was never timed is scored as if it used its whole
    window: no bonus. Withholding the clock must not pay.
    """
    if not game.is_over:
        return None

    game_time_seconds = game.game_time_seconds
    if game_time_seconds is None:
        game_time_seconds = rules.seconds_per_letter * game.word_length

    return score_game(
        rules,
        word_length=game.word_length,
        max_attempts=game.max_attempts,
        is_won=game.is_won,
        winning_attempt=game.winning_attempt,
        game_time_seconds=game_time_seconds,
    )
