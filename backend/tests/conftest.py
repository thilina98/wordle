"""Shared fixtures. Every test builds its own app, so nothing leaks between them."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wordle.app import create_app
from wordle.config import Settings

PASSWORD = "open-sesame"
SECRET_KEY = "test-secret-key-at-least-16"
ORIGIN = "http://localhost:8080"
ANSWERS = ["crane", "state", "tasty", "abbey", "geese"]
# Valid guesses that are deliberately not answers, so tests can tell the two
# lists apart.
EXTRA_GUESSES = ["recan", "cards", "boxes", "zoned"]


def _write(path: Path, words: list[str]) -> Path:
    path.write_text("word\n" + "\n".join(words) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def answers_path(tmp_path) -> Path:
    return _write(tmp_path / "answers.csv", ANSWERS)


@pytest.fixture
def dictionary_path(tmp_path) -> Path:
    return _write(tmp_path / "dictionary.csv", ANSWERS + EXTRA_GUESSES)


@pytest.fixture
def settings(answers_path, dictionary_path) -> Settings:
    return Settings(
        password=PASSWORD,
        secret_key=SECRET_KEY,
        answers_path=answers_path,
        dictionary_path=dictionary_path,
        allowed_origins=[ORIGIN],
        max_attempts=5,
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def anon(app) -> TestClient:
    """Client with no token."""
    return TestClient(app)


def obtain_token(client: TestClient, password: str = PASSWORD) -> str:
    response = client.post("/api/login", json={"password": password})
    assert response.status_code == 200, response.text
    return response.json()["token"]


@pytest.fixture
def client(app) -> TestClient:
    """Client carrying a valid token on every request."""
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {obtain_token(client)}"
    return client


def authed(settings: Settings) -> TestClient:
    """A logged-in client for a one-off settings variation."""
    client = TestClient(create_app(settings))
    client.headers["Authorization"] = f"Bearer {obtain_token(client)}"
    return client


@pytest.fixture
def answer(app):
    """Pin the answer so game outcomes are deterministic."""

    def pin(word: str) -> str:
        app.state.answers.random_word = lambda rng=None: word
        return word

    return pin
