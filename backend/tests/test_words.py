"""Contract tests for word list loading."""

import random

import pytest

from wordle.words import WordListError, WordRepository


def write_csv(tmp_path, body: str):
    path = tmp_path / "words.csv"
    path.write_text(body, encoding="utf-8")
    return path


class TestLoading:
    def test_loads_words_from_csv_with_header(self, tmp_path):
        repo = WordRepository(write_csv(tmp_path, "word\ncrane\nstate\n"))
        assert repo.vocabulary == frozenset({"crane", "state"})

    def test_loads_words_without_header(self, tmp_path):
        repo = WordRepository(write_csv(tmp_path, "crane\nstate\n"))
        assert repo.vocabulary == frozenset({"crane", "state"})

    def test_normalises_case_and_whitespace(self, tmp_path):
        repo = WordRepository(write_csv(tmp_path, "word\n  CRANE  \nState\n"))
        assert repo.vocabulary == frozenset({"crane", "state"})

    def test_ignores_blank_lines(self, tmp_path):
        repo = WordRepository(write_csv(tmp_path, "word\ncrane\n\n\nstate\n"))
        assert len(repo) == 2

    def test_deduplicates(self, tmp_path):
        repo = WordRepository(write_csv(tmp_path, "word\ncrane\ncrane\n"))
        assert len(repo) == 1

    def test_rejects_wrong_length_word_loudly(self, tmp_path):
        # A silently dropped word is a data bug that hides itself.
        with pytest.raises(WordListError, match="knight"):
            WordRepository(write_csv(tmp_path, "word\ncrane\nknight\n"))

    def test_rejects_non_alphabetic_word(self, tmp_path):
        with pytest.raises(WordListError, match="cr4ne"):
            WordRepository(write_csv(tmp_path, "word\ncr4ne\n"))

    def test_reports_the_offending_line_number(self, tmp_path):
        with pytest.raises(WordListError, match="line 3"):
            WordRepository(write_csv(tmp_path, "word\ncrane\nknight\n"))

    def test_rejects_empty_list(self, tmp_path):
        with pytest.raises(WordListError, match="no words"):
            WordRepository(write_csv(tmp_path, "word\n"))

    def test_reports_missing_file(self, tmp_path):
        with pytest.raises(WordListError, match="not found"):
            WordRepository(tmp_path / "absent.csv")

    def test_honours_configured_word_length(self, tmp_path):
        repo = WordRepository(write_csv(tmp_path, "word\ncats\ndogs\n"), word_length=4)
        assert repo.vocabulary == frozenset({"cats", "dogs"})


class TestSelection:
    def test_random_word_comes_from_the_list(self, tmp_path):
        repo = WordRepository(write_csv(tmp_path, "word\ncrane\nstate\n"))
        assert repo.random_word() in repo.vocabulary

    def test_random_word_is_reproducible_with_a_seeded_rng(self, tmp_path):
        repo = WordRepository(write_csv(tmp_path, "word\ncrane\nstate\ntasty\nabbey\n"))
        first = repo.random_word(random.Random(7))
        assert repo.random_word(random.Random(7)) == first

    def test_contains_checks_membership_case_insensitively(self, tmp_path):
        repo = WordRepository(write_csv(tmp_path, "word\ncrane\n"))
        assert "CRANE" in repo
        assert "state" not in repo


class TestShippedList:
    """The list that actually ships must be usable."""

    def test_default_list_loads_and_is_large_enough(self):
        repo = WordRepository.default()
        assert len(repo) >= 200
        assert all(len(w) == 5 and w.isalpha() and w.islower() for w in repo.vocabulary)
