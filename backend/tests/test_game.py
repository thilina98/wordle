"""Contract tests for the game rules. Assert inputs and outputs, not internals."""

import pytest

from wordle.game import Colour, GameOverError, GameState, InvalidGuessError, evaluate_guess

# A guess may be any of these; only some are answers. Deliberately includes
# words a small answer list would not hold, which is the point of the split.
VOCABULARY = frozenset(
    {
        "crane",
        "caner",
        "geese",
        "abbey",
        "babes",
        "state",
        "tasty",
        "cynic",
        "spilt",
        "recan",
        "cards",
        "boxes",
        "trees",
        "zoned",
    }
)

G, Y, X = Colour.HIT, Colour.PRESENT, Colour.MISS


class TestEvaluateGuess:
    def test_exact_match_is_all_hits(self):
        assert evaluate_guess("crane", "crane") == [G, G, G, G, G]

    def test_no_shared_letters_is_all_misses(self):
        assert evaluate_guess("crane", "spilt") == [X, X, X, X, X]

    def test_anagram_marks_every_displaced_letter_present(self):
        assert evaluate_guess("crane", "caner") == [G, Y, Y, Y, Y]

    def test_mixed_hits_and_presents(self):
        assert evaluate_guess("state", "tasty") == [Y, Y, Y, G, X]

    def test_repeated_guess_letter_limited_by_target_count(self):
        # "abbey" holds one 'e'; "geese" offers three, so only the first earns a colour.
        assert evaluate_guess("abbey", "geese") == [X, Y, X, X, X]

    def test_repeated_guess_letter_credited_up_to_target_count(self):
        # "abbey" holds two 'b's: one taken by the hit at index 2, one left for index 0.
        assert evaluate_guess("abbey", "babes") == [Y, Y, G, G, X]

    def test_hit_consumes_the_letter_before_a_present_can(self):
        # "crane" holds one 'c', spent on the hit at index 0, so the trailing 'c' misses.
        assert evaluate_guess("crane", "cynic") == [G, X, Y, X, X]

    def test_is_case_insensitive(self):
        assert evaluate_guess("CRANE", "CrAnE") == [G, G, G, G, G]

    def test_rejects_length_mismatch(self):
        with pytest.raises(ValueError):
            evaluate_guess("crane", "cranes")


class TestGameState:
    def _game(self, target="crane", max_attempts=5):
        return GameState(target=target, vocabulary=VOCABULARY, max_attempts=max_attempts)

    def test_starts_in_progress_with_no_attempts(self):
        game = self._game()
        assert game.attempts == []
        assert game.attempts_remaining == 5
        assert not game.is_over
        assert not game.is_won

    def test_records_attempt_and_returns_colours(self):
        game = self._game()
        attempt = game.guess("caner")
        assert attempt.guess == "caner"
        assert attempt.colours == [G, Y, Y, Y, Y]
        assert game.attempts_remaining == 4
        assert len(game.attempts) == 1

    def test_correct_guess_wins_and_ends_game(self):
        game = self._game()
        game.guess("crane")
        assert game.is_won
        assert game.is_over

    def test_exhausting_attempts_loses(self):
        game = self._game(max_attempts=2)
        game.guess("caner")
        game.guess("geese")
        assert game.is_over
        assert not game.is_won
        assert game.attempts_remaining == 0

    def test_win_on_final_attempt(self):
        game = self._game(max_attempts=2)
        game.guess("caner")
        game.guess("crane")
        assert game.is_won
        assert game.is_over

    def test_guess_normalised_to_lowercase(self):
        assert self._game().guess("CRANE").guess == "crane"

    def test_rejects_wrong_length(self):
        with pytest.raises(InvalidGuessError):
            self._game().guess("cran")

    def test_rejects_non_alphabetic(self):
        with pytest.raises(InvalidGuessError):
            self._game().guess("cr4ne")

    def test_rejects_guess_after_game_over(self):
        game = self._game(max_attempts=1)
        game.guess("caner")
        with pytest.raises(GameOverError):
            game.guess("crane")

    def test_misshapen_guess_does_not_consume_an_attempt(self):
        game = self._game()
        with pytest.raises(InvalidGuessError):
            game.guess("cran")
        assert game.attempts_remaining == 5

    def test_rejects_a_target_that_is_not_a_valid_guess(self):
        # Such a game would be unwinnable.
        with pytest.raises(ValueError):
            GameState(target="zzzzz", vocabulary=VOCABULARY)

    def test_letter_states_track_best_result_per_letter(self):
        game = self._game()
        game.guess("caner")
        game.guess("crane")
        assert game.letter_states["c"] == G
        assert game.letter_states["r"] == G
        assert game.letter_states["a"] == G

    def test_letter_states_records_misses_and_omits_unguessed(self):
        game = self._game()
        game.guess("spilt")
        assert game.letter_states["s"] == X
        assert "c" not in game.letter_states

    def test_rejects_a_non_word(self):
        with pytest.raises(InvalidGuessError, match="Not a valid word"):
            self._game().guess("zzzzz")

    def test_a_real_word_need_not_be_an_answer(self):
        # The whole point of the two lists: guesses draw on the larger one.
        assert self._game().guess("recan").colours == [Y, Y, Y, Y, Y]

    def test_a_non_word_does_not_consume_an_attempt(self):
        game = self._game()
        with pytest.raises(InvalidGuessError):
            game.guess("zzzzz")
        assert game.attempts_remaining == 5

    def test_a_non_word_does_not_colour_the_keyboard(self):
        game = self._game()
        with pytest.raises(InvalidGuessError):
            game.guess("zzzzz")
        assert game.letter_states == {}

    def test_letter_state_never_downgrades(self):
        game = self._game(target="state")
        game.guess("tasty")
        game.guess("state")
        assert game.letter_states["t"] == G
