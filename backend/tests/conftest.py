"""Shared fixtures. Every test builds its own app, so nothing leaks between them."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wordle.app import create_app
from wordle.config import Settings

PASSWORD = "open-sesame"
SECRET_KEY = "test-secret-key-at-least-16"
WORDS = ["crane", "state", "tasty", "abbey", "geese"]

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@pytest.fixture
def word_list(tmp_path) -> Path:
    path = tmp_path / "words.csv"
    path.write_text("word\n" + "\n".join(WORDS) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def settings(word_list) -> Settings:
    return Settings(
        password=PASSWORD,
        secret_key=SECRET_KEY,
        word_list_path=word_list,
        frontend_dir=FRONTEND_DIR,
        max_attempts=5,
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def anon(app):
    """Client with no session."""
    return TestClient(app)


@pytest.fixture
def client(app):
    """Client that has logged in."""
    client = TestClient(app)
    response = client.post("/login", data={"password": PASSWORD})
    assert response.status_code == 200  # followed the redirect to /
    return client


def login(settings: Settings) -> TestClient:
    """A logged-in client for a one-off settings variation."""
    client = TestClient(create_app(settings))
    assert client.post("/login", data={"password": PASSWORD}).status_code == 200
    return client


@pytest.fixture
def answer(app):
    """Pin the answer so game outcomes are deterministic."""

    def pin(word: str) -> str:
        app.state.repository.random_word = lambda rng=None: word
        return word

    return pin
