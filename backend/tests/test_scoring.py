"""Scoring. The table from the spec, then the properties it has to keep."""

from functools import partial

import pytest

from tests.conftest import ANSWERS, EXTRA_GUESSES, RULES
from wordle.game import GameState, InvalidGuessError
from wordle.scoring import score_for as _score_for
from wordle.scoring import score_game as _score_game

DIFFICULTY_STEP = RULES.difficulty_step
NORMAL_MAX_SCORE = RULES.normal_max_score
SECONDS_PER_LETTER = RULES.seconds_per_letter

# Version 1's constants throughout: the spec table below was written for them.
score_game = partial(_score_game, RULES)


def score_for(game: GameState):
    return _score_for(game, RULES)


def play(
    word_length: int,
    max_attempts: int,
    is_won: bool,
    winning_attempt: int | None,
    game_time_seconds: float,
) -> float:
    return score_game(
        word_length=word_length,
        max_attempts=max_attempts,
        is_won=is_won,
        winning_attempt=winning_attempt,
        game_time_seconds=game_time_seconds,
    ).score


@pytest.mark.parametrize(
    ("word_length", "max_attempts", "is_won", "winning_attempt", "game_time_seconds", "expected"),
    [
        (5, 5, True, 2, 0, 10.00),
        (5, 4, True, 2, 0, 12.50),
        (5, 4, True, 3, 120, 6.82),
        (5, 5, True, 5, 300, 1.67),
        # Past the window the bonus stops at zero rather than going negative.
        (5, 5, True, 5, 900, 1.67),
        (6, 6, True, 4, 180, 4.10),
        (7, 6, True, 6, 0, 3.45),
        (4, 5, True, 5, 240, 0.60),
        # Attempt one is luck, not play.
        (5, 5, True, 1, 10, 0.00),
        (5, 5, False, None, 200, 0.00),
    ],
)
def test_spec_table(
    word_length, max_attempts, is_won, winning_attempt, game_time_seconds, expected
):
    assert play(word_length, max_attempts, is_won, winning_attempt, game_time_seconds) == expected


def test_the_best_normal_mode_game_scores_ten_at_every_length():
    """The scale is the point: 10 means the same thing whatever the word."""
    for word_length in range(3, 11):
        assert play(word_length, word_length, True, 2, 0) == NORMAL_MAX_SCORE


def test_fewer_guesses_always_beats_more_however_slow():
    """The time bonus must never outweigh a guess. Checked at the extremes:
    the fast slow guesser against the slowest possible quicker one."""
    for word_length in range(4, 11):
        for max_attempts in (word_length - 1, word_length, word_length + 1):
            for winning_attempt in range(2, max_attempts):
                quicker_but_slowest = play(word_length, max_attempts, True, winning_attempt, 10_000)
                slower_but_instant = play(word_length, max_attempts, True, winning_attempt + 1, 0)
                assert quicker_but_slowest > slower_but_instant


def test_the_difficulty_multiplier_is_the_only_use_of_max_attempts():
    """Same word, same play, fewer attempts allowed: the whole difference is
    the multiplier. Base and bonus must not have noticed."""
    normal = score_game(
        word_length=6, max_attempts=6, is_won=True, winning_attempt=4, game_time_seconds=90
    )
    harder = score_game(
        word_length=6, max_attempts=5, is_won=True, winning_attempt=4, game_time_seconds=90
    )
    assert harder.base == normal.base
    assert harder.time_bonus == normal.time_bonus
    assert harder.multiplier == pytest.approx(normal.multiplier * DIFFICULTY_STEP)
    assert harder.raw_score == pytest.approx(normal.raw_score * DIFFICULTY_STEP)


def test_the_time_window_ignores_the_attempt_allowance():
    """Extra attempts are not extra time."""
    generous = score_game(
        word_length=5, max_attempts=7, is_won=True, winning_attempt=3, game_time_seconds=150
    )
    mean = score_game(
        word_length=5, max_attempts=3, is_won=True, winning_attempt=3, game_time_seconds=150
    )
    assert generous.time_bonus == mean.time_bonus


def test_a_loss_keeps_no_working():
    lost = score_game(
        word_length=5, max_attempts=5, is_won=False, winning_attempt=None, game_time_seconds=200
    )
    assert (lost.base, lost.time_bonus, lost.multiplier, lost.raw_score) == (0.0, 0.0, 0.0, 0.0)
    assert lost.winning_attempt is None


def test_the_score_is_rounded_once_at_the_end():
    """Full precision through every term; two places only on the total."""
    scored = score_game(
        word_length=5, max_attempts=4, is_won=True, winning_attempt=3, game_time_seconds=120
    )
    assert scored.base != round(scored.base, 2)
    assert scored.score == round(scored.score, 2)


# --- Scoring a real game --------------------------------------------------


def _game(target: str = "crane", **kwargs) -> GameState:
    return GameState(target=target, vocabulary=set(ANSWERS + EXTRA_GUESSES), **kwargs)


def test_a_game_in_progress_has_no_score():
    game = _game()
    assert score_for(game) is None
    game.guess("state", now=0.0)
    assert score_for(game) is None


def test_a_won_game_scores_on_the_clock_it_was_played_with():
    game = _game()
    game.start_timer(1000.0)
    game.guess("state", now=1010.0)
    game.guess("crane", now=1060.0)

    scored = score_for(game)
    assert scored.is_won
    assert scored.winning_attempt == 2
    assert scored.game_time_seconds == 60.0
    assert scored.score == play(5, 5, True, 2, 60.0)


def test_an_untimed_game_gets_no_time_bonus():
    """Never signalling a start must not be worth more than playing fast."""
    game = _game()
    game.guess("state")
    game.guess("crane")

    scored = score_for(game)
    assert scored.is_won
    assert scored.time_bonus == 0.0
    assert scored.game_time_seconds == SECONDS_PER_LETTER * 5


def test_the_timer_starts_at_the_first_guess_if_nobody_started_it():
    game = _game()
    game.guess("state", now=500.0)
    game.guess("crane", now=560.0)
    assert game.game_time_seconds == 60.0


def test_starting_the_timer_twice_keeps_the_first_reading():
    game = _game()
    game.start_timer(100.0)
    game.start_timer(999.0)
    game.guess("crane", now=130.0)
    assert game.game_time_seconds == 30.0


def test_a_rejected_guess_does_not_move_the_clock():
    game = _game()
    game.start_timer(0.0)
    with pytest.raises(InvalidGuessError):
        game.guess("zzzzz", now=50.0)
    assert game.finished_at is None
