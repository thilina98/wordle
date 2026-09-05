"""Word list access.

Two lists, because they do different jobs:

- **answers** — a small, curated set of common words. Targets come from here,
  so nobody has to guess an obscure one.
- **dictionary** — every word a guess is allowed to be. Much larger, so a
  player typing a real word is not told it is wrong.

The answers are a subset of the dictionary; `WordRepository.default_pair`
checks that on load. The CSV is the only storage today. Everything else depends
on this class rather than on a file, so swapping in a database later is a
change confined here.
"""

from __future__ import annotations

import csv
import random
from collections.abc import Iterator
from importlib import resources
from pathlib import Path

from .game import WORD_LENGTH

_HEADER = "word"


class WordListError(Exception):
    """The word list is missing or malformed."""


class WordRepository:
    """An immutable, validated collection of playable words."""

    def __init__(self, path: str | Path, word_length: int = WORD_LENGTH) -> None:
        self._path = Path(path)
        self._word_length = word_length
        self._words = self._load()
        self._vocabulary = frozenset(self._words)

    def _load(self) -> tuple[str, ...]:
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise WordListError(f"Word list not found: {self._path}") from exc
        except OSError as exc:
            raise WordListError(f"Could not read word list {self._path}: {exc}") from exc

        words: set[str] = set()
        reader = csv.reader(text.splitlines())
        for line, row in enumerate(reader, start=1):
            if not row or not row[0].strip():
                continue
            word = row[0].strip().lower()
            if line == 1 and word == _HEADER:
                continue
            # Loud rather than silent: a dropped word is a data bug that hides itself.
            if len(word) != self._word_length or not word.isalpha():
                raise WordListError(
                    f"{self._path}: line {line}: {word!r} is not a "
                    f"{self._word_length}-letter alphabetic word"
                )
            words.add(word)

        if not words:
            raise WordListError(f"{self._path} contains no words")
        return tuple(sorted(words))

    @classmethod
    def packaged(cls, filename: str, word_length: int = WORD_LENGTH) -> WordRepository:
        """A list shipped inside the package."""
        with resources.as_file(resources.files("wordle.data") / filename) as path:
            return cls(path, word_length=word_length)

    @classmethod
    def default_pair(cls, word_length: int = WORD_LENGTH) -> tuple[WordRepository, WordRepository]:
        """The shipped (answers, dictionary) pair.

        An answer that is not an allowed guess would be unwinnable, so that is
        checked here rather than discovered by a player.
        """
        answers = cls.packaged("answers.csv", word_length=word_length)
        dictionary = cls.packaged("dictionary.csv", word_length=word_length)
        stray = answers.vocabulary - dictionary.vocabulary
        if stray:
            raise WordListError(
                f"{len(stray)} answer(s) missing from the dictionary: "
                f"{', '.join(sorted(stray)[:5])}"
            )
        return answers, dictionary

    @property
    def vocabulary(self) -> frozenset[str]:
        return self._vocabulary

    @property
    def word_length(self) -> int:
        return self._word_length

    def random_word(self, rng: random.Random | None = None) -> str:
        return (rng or random).choice(self._words)

    def __contains__(self, word: object) -> bool:
        return isinstance(word, str) and word.strip().lower() in self._vocabulary

    def __len__(self) -> int:
        return len(self._words)

    def __iter__(self) -> Iterator[str]:
        return iter(self._words)
