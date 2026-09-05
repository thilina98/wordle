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
def settings(answers_path, dictionary_path, tmp_path) -> Settings:
    return Settings(
        password=PASSWORD,
        secret_key=SECRET_KEY,
        answers_path=answers_path,
        dictionary_path=dictionary_path,
        allowed_origins=[ORIGIN],
        max_attempts=5,
        data_dir=tmp_path / "state",
    )


@pytest.fixture
def app(settings):
    app = create_app(settings)
    yield app
    # The sqlite store holds an open connection; tests do not run lifespan.
    close = getattr(app.state.store, "close", None)
    if close:
        close()


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


@pytest.fixture
def make_client():
    """Build clients for one-off settings variations, and clean them up.

    The sqlite store keeps a connection open, so every app a test builds has
    to be closed or the suite leaks file descriptors.
    """
    built = []

    def build(settings: Settings, login: bool = True) -> TestClient:
        app = create_app(settings)
        built.append(app)
        client = TestClient(app)
        if login:
            client.headers["Authorization"] = f"Bearer {obtain_token(client)}"
        return client

    yield build
    for app in built:
        close = getattr(app.state.store, "close", None)
        if close:
            close()


@pytest.fixture
def answer(app):
    """Pin the answer so game outcomes are deterministic."""

    def pin(word: str) -> str:
        app.state.answers.random_word = lambda rng=None: word
        return word

    return pin
