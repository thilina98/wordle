"""Game rules. Pure domain logic: no I/O, no framework, no globals."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass, field
from enum import StrEnum

WORD_LENGTH = 5

# Attempts are not configured, they are derived: a game gets one guess per
# letter, and may be made easier by at most two more. A longer word is a harder
# word, so the allowance travels with the length instead of being a flat number
# that is generous for four letters and stingy for seven.
#
# Two is the floor because a single guess is not a game: with no feedback to
# act on, the player can only be lucky.
MIN_ATTEMPTS = 2
ATTEMPT_ALLOWANCE = 2


class Colour(StrEnum):
    """Feedback for one letter. The frontend maps these to actual colours."""

    HIT = "hit"  # right letter, right place
    PRESENT = "present"  # right letter, wrong place
    MISS = "miss"  # letter not available


# Ranked worst to best, so a letter's known state can only improve.
_RANK = {Colour.MISS: 0, Colour.PRESENT: 1, Colour.HIT: 2}


class GameError(Exception):
    """Base for rule violations. Carries a player-facing message."""


class InvalidGuessError(GameError):
    """The guess is not a playable word."""


class GameOverError(GameError):
    """The game has already finished."""


def evaluate_guess(target: str, guess: str) -> list[Colour]:
    """Colour each letter of `guess` against `target`.

    Two passes, because a letter can only be credited once. Exact matches claim
    their letter first; leftovers are what a displaced letter may draw from.
    """
    target, guess = target.lower(), guess.lower()
    if len(target) != len(guess):
        raise ValueError(f"guess must be {len(target)} letters, got {len(guess)}")

    colours = [Colour.MISS] * len(guess)

    # Pass one: exact positions, and tally what each remaining letter leaves behind.
    unclaimed = Counter()
    for i, (want, got) in enumerate(zip(target, guess, strict=True)):
        if want == got:
            colours[i] = Colour.HIT
        else:
            unclaimed[want] += 1

    # Pass two: displaced letters draw from the leftovers, first come first served.
    for i, got in enumerate(guess):
        if colours[i] is Colour.HIT:
            continue
        if unclaimed[got] > 0:
            unclaimed[got] -= 1
            colours[i] = Colour.PRESENT

    return colours


def default_attempts(word_length: int) -> int:
    """One guess per letter."""
    return word_length


def attempt_limit(word_length: int) -> int:
    """The most guesses a word of this length may be played with."""
    return default_attempts(word_length) + ATTEMPT_ALLOWANCE


class Difficulty(StrEnum):
    """How generous a game's attempt allowance is, against its word length.

    Mode is the word length; difficulty is never the length. A label, not a
    number of attempts, because the same count means different things at
    different lengths: four attempts is hard for five letters and normal for
    four.
    """

    EASY = "easy"  # more attempts than letters
    NORMAL = "normal"  # one attempt per letter
    HARD = "hard"  # fewer attempts than letters


def difficulty_of(word_length: int, max_attempts: int) -> Difficulty:
    """The difficulty a game of this shape is played at.

    A recorded game keeps the label it was given, so changing this mapping
    relabels future games only.
    """
    normal = default_attempts(word_length)
    if max_attempts > normal:
        return Difficulty.EASY
    if max_attempts < normal:
        return Difficulty.HARD
    return Difficulty.NORMAL


@dataclass(frozen=True, slots=True)
class Attempt:
    """One scored guess."""

    guess: str
    colours: list[Colour]


@dataclass(slots=True)
class GameState:
    """A single game in progress. Mutated only through `guess`.

    `vocabulary` is the set of words a guess may be, which is far larger than
    the set of words the answer is drawn from. Answers are common words;
    guesses only have to be real ones.
    """

    target: str
    vocabulary: Collection[str]
    #: None means the default for this word's length: one guess per letter.
    max_attempts: int | None = None
    attempts: list[Attempt] = field(default_factory=list)
    #: When the player started playing, by whatever clock the caller keeps.
    #: Set through `start_timer`, or on the first guess if nobody did.
    started_at: float | None = None
    #: When the game ended. Set by the guess that ended it.
    finished_at: float | None = None

    def __post_init__(self) -> None:
        self.target = self.target.lower()
        if self.target not in self.vocabulary:
            raise ValueError(f"target {self.target!r} is not a valid guess")
        if self.max_attempts is None:
            self.max_attempts = default_attempts(self.word_length)
        limit = attempt_limit(self.word_length)
        if not MIN_ATTEMPTS <= self.max_attempts <= limit:
            # Enforced here rather than at the HTTP edge, so no caller and no
            # stored row can produce a game nobody could lose. The limit tracks
            # the word, which is why it cannot live in configuration.
            raise ValueError(
                f"a {self.word_length}-letter game allows between {MIN_ATTEMPTS} and "
                f"{limit} attempts, got {self.max_attempts}"
            )

    @property
    def word_length(self) -> int:
        return len(self.target)

    @property
    def attempt_limit(self) -> int:
        """The most attempts this game could have been given."""
        return attempt_limit(self.word_length)

    @property
    def difficulty(self) -> Difficulty:
        return difficulty_of(self.word_length, self.max_attempts)

    @property
    def is_won(self) -> bool:
        return bool(self.attempts) and self.attempts[-1].guess == self.target

    @property
    def is_over(self) -> bool:
        return self.is_won or len(self.attempts) >= self.max_attempts

    @property
    def attempts_remaining(self) -> int:
        return max(0, self.max_attempts - len(self.attempts))

    @property
    def winning_attempt(self) -> int | None:
        """Which attempt won it, counting from 1. None if it was not won."""
        return len(self.attempts) if self.is_won else None

    @property
    def game_time_seconds(self) -> float | None:
        """How long the game took, or None while it is still running.

        Measured from the moment the player committed to playing -- the first
        keystroke, if the caller said so -- to the guess that ended it. It
        never pauses: a game left open is a game still being played.
        """
        if self.started_at is None or self.finished_at is None:
            return None
        return max(0.0, self.finished_at - self.started_at)

    def start_timer(self, now: float) -> None:
        """Mark the start of play. The first call wins; later ones do nothing.

        Idempotent because the client calls it on the first keystroke and has
        no cheap way to know whether that keystroke was really the first.
        """
        if self.started_at is None:
            self.started_at = now

    @property
    def letter_states(self) -> dict[str, Colour]:
        """Best result seen so far per letter, for colouring the keyboard."""
        states: dict[str, Colour] = {}
        for attempt in self.attempts:
            for letter, colour in zip(attempt.guess, attempt.colours, strict=True):
                if letter not in states or _RANK[colour] > _RANK[states[letter]]:
                    states[letter] = colour
        return states

    def guess(self, word: str, now: float | None = None) -> Attempt:
        """Score a guess and record it.

        `now` is a clock reading, which the caller supplies rather than the
        game reading one itself: the domain stays pure, and a test can play a
        whole game in whatever time it likes. Passing None leaves the timer
        alone, so a caller that does not care about scoring can ignore it.

        Raises GameOverError if the game has finished, InvalidGuessError if the
        guess is the wrong shape or not a real word. Neither consumes an
        attempt, and neither moves the clock.
        """
        if self.is_over:
            raise GameOverError("This game has already finished")

        word = word.strip().lower()
        if len(word) != self.word_length:
            raise InvalidGuessError(f"Guess must be {self.word_length} letters")
        if not word.isalpha():
            raise InvalidGuessError("Guess must contain letters only")
        if word not in self.vocabulary:
            raise InvalidGuessError("Enter a valid word")

        attempt = Attempt(guess=word, colours=evaluate_guess(self.target, word))
        self.attempts.append(attempt)
        if now is not None:
            # A client that never signalled its first keystroke still gets a
            # timed game, just one that misses the thinking before guess one.
            self.start_timer(now)
            if self.is_over:
                self.finished_at = now
        return attempt
