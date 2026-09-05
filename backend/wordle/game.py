"""Game rules. Pure domain logic: no I/O, no framework, no globals."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass, field
from enum import StrEnum

WORD_LENGTH = 5
MAX_ATTEMPTS = 5


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
    max_attempts: int = MAX_ATTEMPTS
    attempts: list[Attempt] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.target = self.target.lower()
        if self.target not in self.vocabulary:
            raise ValueError(f"target {self.target!r} is not a valid guess")

    @property
    def word_length(self) -> int:
        return len(self.target)

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
    def letter_states(self) -> dict[str, Colour]:
        """Best result seen so far per letter, for colouring the keyboard."""
        states: dict[str, Colour] = {}
        for attempt in self.attempts:
            for letter, colour in zip(attempt.guess, attempt.colours, strict=True):
                if letter not in states or _RANK[colour] > _RANK[states[letter]]:
                    states[letter] = colour
        return states

    def guess(self, word: str) -> Attempt:
        """Score a guess and record it.

        Raises GameOverError if the game has finished, InvalidGuessError if the
        guess is the wrong shape or not a real word. Neither consumes an
        attempt.
        """
        if self.is_over:
            raise GameOverError("This game has already finished")

        word = word.strip().lower()
        if len(word) != self.word_length:
            raise InvalidGuessError(f"Guess must be {self.word_length} letters")
        if not word.isalpha():
            raise InvalidGuessError("Guess must contain letters only")
        if word not in self.vocabulary:
            raise InvalidGuessError("Not a valid word")

        attempt = Attempt(guess=word, colours=evaluate_guess(self.target, word))
        self.attempts.append(attempt)
        return attempt
