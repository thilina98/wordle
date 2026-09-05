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


class TestShippedLists:
    """The lists that actually ship must be usable, and consistent with each other."""

    def test_both_lists_load(self):
        answers, dictionary = WordRepository.default_pair()
        for repo in (answers, dictionary):
            assert all(len(w) == 5 and w.isalpha() and w.islower() for w in repo.vocabulary)

    def test_answer_list_is_a_sensible_size(self):
        answers, _ = WordRepository.default_pair()
        assert len(answers) >= 200

    def test_dictionary_is_much_larger_than_the_answer_list(self):
        # A dictionary the size of the answer list would reject real words,
        # which is the whole reason the two are separate.
        answers, dictionary = WordRepository.default_pair()
        assert len(dictionary) > 10 * len(answers)

    def test_every_answer_is_an_allowed_guess(self):
        answers, dictionary = WordRepository.default_pair()
        assert answers.vocabulary <= dictionary.vocabulary

    def test_dictionary_holds_ordinary_words_the_answer_list_does_not(self):
        answers, dictionary = WordRepository.default_pair()
        for word in ("cards", "boxes", "trees", "email", "fjord"):
            assert word in dictionary, word

    def test_dictionary_rejects_letter_soup(self):
        _, dictionary = WordRepository.default_pair()
        for junk in ("zzzzz", "qwrtp", "aeiou"):
            assert junk not in dictionary, junk

    def test_mismatched_pair_is_reported(self, tmp_path, monkeypatch):
        # An answer outside the dictionary would be an unwinnable game.
        answers = tmp_path / "answers.csv"
        answers.write_text("word\ncrane\nzoned\n", encoding="utf-8")
        dictionary = tmp_path / "dictionary.csv"
        dictionary.write_text("word\ncrane\n", encoding="utf-8")

        real = WordRepository.packaged
        monkeypatch.setattr(
            WordRepository,
            "packaged",
            classmethod(
                lambda cls, filename, word_length=5: cls(
                    answers if "answers" in filename else dictionary, word_length=word_length
                )
            ),
        )
        with pytest.raises(WordListError, match="zoned"):
            WordRepository.default_pair()
        monkeypatch.setattr(WordRepository, "packaged", real)
