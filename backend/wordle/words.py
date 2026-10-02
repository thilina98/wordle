"""Word list access.

Two lists per length, because they do different jobs:

- **answers** — a small, curated set of common words. Targets come from here,
  so nobody has to guess an obscure one.
- **dictionary** — every word a guess is allowed to be. Much larger, so a
  player typing a real word is not told it is wrong.

`WordRepository` is one such list. `WordCatalogue` holds every length the
deployment has installed and is what the rest of the application talks to, so
a game's length is a per-game fact rather than a property of the process.

Word length is a property of the data, never configured separately: a list
reads its length off its first word and every later word must agree, and a
list found in a directory named for a length must match that name. A list that
disagrees fails on load instead of at the first guess.

On disk, one directory per length:

    data/5/answers.csv
    data/5/dictionary.csv
    data/6/answers.csv
    data/6/dictionary.csv

Adding a length is adding a directory. No code changes.
"""

from __future__ import annotations

import csv
import random
from collections.abc import Iterator, Mapping
from importlib import resources
from pathlib import Path

_HEADER = "word"
_ANSWERS = "answers.csv"
_DICTIONARY = "dictionary.csv"
PREFERRED_LENGTH = 5


class WordListError(Exception):
    """The word list is missing or malformed."""


class WordRepository:
    """An immutable, validated collection of playable words."""

    def __init__(self, path: str | Path, word_length: int | None = None) -> None:
        """`word_length` None reads the length off the list; an int requires it."""
        self._path = Path(path)
        self._expected_length = word_length
        self._words = self._load()
        self._word_length = len(self._words[0])
        self._vocabulary = frozenset(self._words)

    def _load(self) -> tuple[str, ...]:
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise WordListError(f"Word list not found: {self._path}") from exc
        except OSError as exc:
            raise WordListError(f"Could not read word list {self._path}: {exc}") from exc

        words: set[str] = set()
        # None until the first word fixes it, unless the caller named one.
        length = self._expected_length
        reader = csv.reader(text.splitlines())
        for line, row in enumerate(reader, start=1):
            if not row or not row[0].strip():
                continue
            word = row[0].strip().lower()
            if line == 1 and word == _HEADER:
                continue
            if not word.isalpha():
                raise WordListError(
                    f"{self._path}: line {line}: {word!r} is not an alphabetic word"
                )
            if length is None:
                length = len(word)
            # Loud rather than silent: a dropped word is a data bug that hides itself.
            if len(word) != length:
                raise WordListError(
                    f"{self._path}: line {line}: {word!r} is not a {length}-letter word"
                )
            words.add(word)

        if not words:
            raise WordListError(f"{self._path} contains no words")
        return tuple(sorted(words))

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


class WordCatalogue:
    """The word lists this deployment has installed, indexed by length.

    One small interface over however many lists are installed: callers ask for
    a length and get the pair for it, or ask what lengths exist. Nothing above
    this class reads a file or knows where the lists came from.
    """

    def __init__(
        self,
        pairs: Mapping[int, tuple[WordRepository, WordRepository]],
        default_length: int | None = None,
    ) -> None:
        if not pairs:
            raise WordListError("A catalogue needs at least one word length")
        for length, (answers, dictionary) in pairs.items():
            _check_pair(length, answers, dictionary)
        self._pairs = dict(sorted(pairs.items()))
        self._default_length = self._resolve_default(default_length)

    def _resolve_default(self, requested: int | None) -> int:
        if requested is None:
            # Five is ordinary Wordle, so prefer it when it is installed.
            return PREFERRED_LENGTH if PREFERRED_LENGTH in self._pairs else min(self._pairs)
        if requested not in self._pairs:
            raise WordListError(
                f"No {requested}-letter word list. Installed: {self.describe_lengths()}"
            )
        return requested

    @classmethod
    def from_directory(cls, root: str | Path, default_length: int | None = None) -> WordCatalogue:
        """Load every `<length>/` directory under `root`.

        Directories that are not named for a number are ignored, so unrelated
        files can live alongside the lists.
        """
        root = Path(root)
        if not root.is_dir():
            raise WordListError(f"Word list directory not found: {root}")

        pairs: dict[int, tuple[WordRepository, WordRepository]] = {}
        for child in sorted(root.iterdir()):
            if not child.is_dir() or not child.name.isdigit():
                continue
            length = int(child.name)
            # The directory name is the assertion: a list that disagrees with
            # the name it is filed under is a data bug, not a new length.
            pairs[length] = (
                WordRepository(child / _ANSWERS, word_length=length),
                WordRepository(child / _DICTIONARY, word_length=length),
            )

        if not pairs:
            raise WordListError(
                f"{root} has no word lists. Expected at least one directory named "
                f"for a length, e.g. {root / '5'}/{_ANSWERS}"
            )
        return cls(pairs, default_length=default_length)

    @classmethod
    def packaged(cls, default_length: int | None = None) -> WordCatalogue:
        """The lists shipped inside the package."""
        with resources.as_file(resources.files("wordle.data")) as root:
            return cls.from_directory(root, default_length=default_length)

    @property
    def lengths(self) -> tuple[int, ...]:
        return tuple(self._pairs)

    @property
    def default_length(self) -> int:
        return self._default_length

    def describe_lengths(self) -> str:
        """For error messages aimed at whoever configured the deployment."""
        return ", ".join(str(n) for n in self._pairs)

    def answers(self, length: int | None = None) -> WordRepository:
        return self._pair(length)[0]

    def dictionary(self, length: int | None = None) -> WordRepository:
        return self._pair(length)[1]

    def vocabulary_for(self, length: int) -> frozenset[str]:
        """Allowed guesses at `length`. Raises KeyError if nothing is installed.

        This is the shape the game store wants: it knows a stored target's
        length and needs the words that target was legal under.
        """
        return self._pairs[length][1].vocabulary

    def _pair(self, length: int | None) -> tuple[WordRepository, WordRepository]:
        length = self._default_length if length is None else length
        try:
            return self._pairs[length]
        except KeyError as exc:
            raise KeyError(
                f"No {length}-letter word list. Installed: {self.describe_lengths()}"
            ) from exc

    def __contains__(self, length: object) -> bool:
        return length in self._pairs

    def __len__(self) -> int:
        return len(self._pairs)


def _check_pair(length: int, answers: WordRepository, dictionary: WordRepository) -> None:
    """An answer outside the dictionary would be an unwinnable game."""
    for role, repo in (("answers", answers), ("dictionary", dictionary)):
        if repo.word_length != length:
            raise WordListError(
                f"{length}-letter {role} list holds {repo.word_length}-letter words"
            )
    stray = answers.vocabulary - dictionary.vocabulary
    if stray:
        raise WordListError(
            f"{len(stray)} {length}-letter answer(s) missing from the dictionary: "
            f"{', '.join(sorted(stray)[:5])}"
        )
