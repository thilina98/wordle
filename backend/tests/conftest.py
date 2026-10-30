"""Shared fixtures. Every test builds its own app, so nothing leaks between them."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.fakes import FakeIdentityProvider
from wordle.accounts import Accounts, InMemoryPlayerRepository
from wordle.app import create_app
from wordle.config import Settings
from wordle.scoring import ScoringRules
from wordle.stats import FixedScoringRules, InMemoryPlayerStats

ORIGIN = "http://localhost:8080"
#: Scoring version 1, as data script 0001_seed_scoring_version_1 seeds it.
RULES = ScoringRules(
    max_base=100.0,
    last_attempt_ratio=0.2,
    time_bonus_cap=0.20,
    seconds_per_letter=60.0,
    difficulty_step=1.25,
    normal_max_score=10.0,
    score_precision=2,
    version=1,
)
#: The same rules as WORDLE_SCORING_* settings, for running without a database.
SCORING_SETTINGS = {
    f"scoring_{name}" if name != "score_precision" else "scoring_precision": getattr(RULES, name)
    for name in (
        "max_base",
        "last_attempt_ratio",
        "time_bonus_cap",
        "seconds_per_letter",
        "difficulty_step",
        "normal_max_score",
        "score_precision",
    )
}
ANSWERS = ["crane", "state", "tasty", "abbey", "geese"]
# Valid guesses that are deliberately not answers, so tests can tell the two
# lists apart.
EXTRA_GUESSES = ["recan", "cards", "boxes", "zoned"]


def _write(path: Path, words: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("word\n" + "\n".join(words) + "\n", encoding="utf-8")
    return path


def write_length(root: Path, length: int, answers: list[str], extra_guesses: list[str]) -> Path:
    """Install one length into a word list directory, the way deployments do."""
    _write(root / str(length) / "answers.csv", answers)
    _write(root / str(length) / "dictionary.csv", answers + extra_guesses)
    return root


@pytest.fixture
def word_lists_dir(tmp_path) -> Path:
    return write_length(tmp_path / "words", 5, ANSWERS, EXTRA_GUESSES)


@pytest.fixture
def settings(word_lists_dir, tmp_path) -> Settings:
    # _env_file=None: never read the developer's real backend/.env, which may
    # turn sign-in on and point at a real database.
    return Settings(
        _env_file=None,
        word_lists_dir=word_lists_dir,
        allowed_origins=[ORIGIN],
        # max_attempts left unset: games derive it from their word length.
        active_games_db_path=tmp_path / "state" / "games.db",
        **SCORING_SETTINGS,
    )


@pytest.fixture
def provider() -> FakeIdentityProvider:
    return FakeIdentityProvider()


@pytest.fixture
def players() -> InMemoryPlayerRepository:
    return InMemoryPlayerRepository()


@pytest.fixture
def accounts(provider, players) -> Accounts:
    return Accounts(provider, players)


@pytest.fixture
def scoring_rules() -> FixedScoringRules:
    return FixedScoringRules(RULES)


@pytest.fixture
def stats(scoring_rules) -> InMemoryPlayerStats:
    return InMemoryPlayerStats(scoring_rules)


@pytest.fixture
def app(settings, accounts, stats, scoring_rules):
    app = create_app(settings, accounts=accounts, stats=stats, scoring_rules=scoring_rules)
    yield app
    # The sqlite store holds an open connection; tests do not run lifespan.
    close = getattr(app.state.store, "close", None)
    if close:
        close()


@pytest.fixture
def client(app) -> TestClient:
    """An anonymous player: no token, which is how most people play."""
    return TestClient(app)


@pytest.fixture
def sign_in(app, provider):
    """A client signed in as a given person at the fake identity provider."""

    def build(subject: str, **profile) -> TestClient:
        client = TestClient(app)
        client.headers["Authorization"] = f"Bearer {provider.person(subject, **profile)}"
        return client

    return build


@pytest.fixture
def make_client():
    """Build clients for one-off settings variations, and clean them up.

    The sqlite store keeps a connection open, so every app a test builds has
    to be closed or the suite leaks file descriptors.
    """
    built = []

    def build(settings: Settings) -> TestClient:
        app = create_app(settings)
        built.append(app)
        return TestClient(app)

    yield build
    for app in built:
        close = getattr(app.state.store, "close", None)
        if close:
            close()


@pytest.fixture
def answer(app):
    """Pin the answer so game outcomes are deterministic."""

    def pin(word: str) -> str:
        app.state.catalogue.answers(len(word)).random_word = lambda rng=None: word
        return word

    return pin
