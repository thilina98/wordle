"""Contract tests for word list loading."""

import random

import pytest

from wordle.words import WordCatalogue, WordListError, WordRepository


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

    def test_infers_word_length_from_the_list(self, tmp_path):
        repo = WordRepository(write_csv(tmp_path, "word\ncats\ndogs\n"))
        assert repo.word_length == 4

    def test_configured_word_length_rejects_a_list_that_disagrees(self, tmp_path):
        with pytest.raises(WordListError, match="5-letter"):
            WordRepository(write_csv(tmp_path, "word\ncats\ndogs\n"), word_length=5)

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
        catalogue = WordCatalogue.packaged()
        for repo in (catalogue.answers(5), catalogue.dictionary(5)):
            assert all(len(w) == 5 and w.isalpha() and w.islower() for w in repo.vocabulary)

    def test_answer_list_is_a_sensible_size(self):
        answers = WordCatalogue.packaged().answers(5)
        assert len(answers) >= 200

    def test_dictionary_is_much_larger_than_the_answer_list(self):
        # A dictionary the size of the answer list would reject real words,
        # which is the whole reason the two are separate.
        catalogue = WordCatalogue.packaged()
        assert len(catalogue.dictionary(5)) > 10 * len(catalogue.answers(5))

    def test_every_answer_is_an_allowed_guess(self):
        catalogue = WordCatalogue.packaged()
        assert catalogue.answers(5).vocabulary <= catalogue.dictionary(5).vocabulary

    def test_dictionary_holds_ordinary_words_the_answer_list_does_not(self):
        dictionary = WordCatalogue.packaged().dictionary(5)
        for word in ("cards", "boxes", "trees", "email", "fjord"):
            assert word in dictionary, word

    def test_dictionary_rejects_letter_soup(self):
        dictionary = WordCatalogue.packaged().dictionary(5)
        for junk in ("zzzzz", "qwrtp", "aeiou"):
            assert junk not in dictionary, junk

    def test_five_is_the_default_length(self):
        assert WordCatalogue.packaged().default_length == 5


class TestWordCatalogue:
    """The registry of lengths the deployment can serve."""

    def install(self, root, length, answers, extra_guesses=()):
        directory = root / str(length)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "answers.csv").write_text(
            "word\n" + "\n".join(answers) + "\n", encoding="utf-8"
        )
        (directory / "dictionary.csv").write_text(
            "word\n" + "\n".join([*answers, *extra_guesses]) + "\n", encoding="utf-8"
        )
        return root

    def test_loads_every_length_directory(self, tmp_path):
        self.install(tmp_path, 4, ["cats", "dogs"])
        self.install(tmp_path, 5, ["crane", "state"])
        catalogue = WordCatalogue.from_directory(tmp_path)
        assert catalogue.lengths == (4, 5)
        assert catalogue.answers(4).vocabulary == frozenset({"cats", "dogs"})
        assert catalogue.answers(5).vocabulary == frozenset({"crane", "state"})

    def test_lengths_are_independent(self, tmp_path):
        self.install(tmp_path, 4, ["cats"], extra_guesses=["rats"])
        self.install(tmp_path, 6, ["clever"], extra_guesses=["batter"])
        catalogue = WordCatalogue.from_directory(tmp_path)
        assert "rats" in catalogue.dictionary(4)
        assert "rats" not in catalogue.dictionary(6)

    def test_defaults_to_five_when_installed(self, tmp_path):
        self.install(tmp_path, 4, ["cats"])
        self.install(tmp_path, 5, ["crane"])
        self.install(tmp_path, 6, ["clever"])
        assert WordCatalogue.from_directory(tmp_path).default_length == 5

    def test_defaults_to_the_shortest_when_five_is_absent(self, tmp_path):
        self.install(tmp_path, 6, ["clever"])
        self.install(tmp_path, 7, ["cleaver"])
        assert WordCatalogue.from_directory(tmp_path).default_length == 6

    def test_an_explicit_default_must_be_installed(self, tmp_path):
        self.install(tmp_path, 5, ["crane"])
        with pytest.raises(WordListError, match="No 6-letter word list"):
            WordCatalogue.from_directory(tmp_path, default_length=6)

    def test_a_list_must_match_the_directory_it_is_filed_under(self, tmp_path):
        self.install(tmp_path, 6, ["crane", "state"])
        with pytest.raises(WordListError, match="6-letter"):
            WordCatalogue.from_directory(tmp_path)

    def test_ignores_directories_not_named_for_a_length(self, tmp_path):
        self.install(tmp_path, 5, ["crane"])
        (tmp_path / "notes").mkdir()
        (tmp_path / "notes" / "README.md").write_text("ignore me", encoding="utf-8")
        assert WordCatalogue.from_directory(tmp_path).lengths == (5,)

    def test_a_directory_with_no_lengths_is_reported(self, tmp_path):
        (tmp_path / "notes").mkdir()
        with pytest.raises(WordListError, match="no word lists"):
            WordCatalogue.from_directory(tmp_path)

    def test_missing_directory_is_reported(self, tmp_path):
        with pytest.raises(WordListError, match="not found"):
            WordCatalogue.from_directory(tmp_path / "absent")

    def test_an_unwinnable_answer_is_reported(self, tmp_path):
        # An answer outside the dictionary would be an unwinnable game.
        directory = tmp_path / "5"
        directory.mkdir()
        (directory / "answers.csv").write_text("word\ncrane\nzoned\n", encoding="utf-8")
        (directory / "dictionary.csv").write_text("word\ncrane\n", encoding="utf-8")
        with pytest.raises(WordListError, match="zoned"):
            WordCatalogue.from_directory(tmp_path)

    def test_unknown_length_names_what_is_installed(self, tmp_path):
        self.install(tmp_path, 5, ["crane"])
        catalogue = WordCatalogue.from_directory(tmp_path)
        with pytest.raises(KeyError, match="Installed: 5"):
            catalogue.answers(9)
