"""End-to-end tests over the HTTP surface: the gate, then the game."""

import time

from fastapi.testclient import TestClient

from tests.conftest import ORIGIN, PASSWORD, authed, obtain_token
from wordle.app import create_app
from wordle.security import issue_token


def new_game(client) -> dict:
    response = client.post("/api/games")
    assert response.status_code == 201
    return response.json()


def guess(client, game_id: str, word: str):
    return client.post(f"/api/games/{game_id}/guesses", json={"guess": word})


class TestServesJsonOnly:
    """The frontend is a separate application. This one hands out no pages."""

    def test_serves_no_html_pages(self, anon):
        for path in ("/", "/login", "/index.html"):
            assert anon.get(path).status_code == 404

    def test_serves_no_static_assets(self, anon):
        for path in ("/static/app.js", "/static/style.css", "/app.js"):
            assert anon.get(path).status_code == 404

    def test_health_check_is_public(self, anon):
        assert anon.get("/healthz").json() == {"status": "ok"}

    def test_api_docs_are_not_exposed(self, anon):
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert anon.get(path).status_code == 404


class TestLogin:
    def test_correct_password_returns_a_token(self, anon):
        response = anon.post("/api/login", json={"password": PASSWORD})
        assert response.status_code == 200
        body = response.json()
        assert body["token"]
        assert body["expires_in"] > 0

    def test_wrong_password_is_rejected(self, anon):
        response = anon.post("/api/login", json={"password": "guess"})
        assert response.status_code == 401
        assert response.json()["detail"] == "Wrong password"

    def test_empty_password_is_rejected(self, anon):
        assert anon.post("/api/login", json={"password": ""}).status_code == 401

    def test_login_needs_a_password_field(self, anon):
        assert anon.post("/api/login", json={}).status_code == 422

    def test_never_echoes_the_password_back(self, anon):
        assert PASSWORD not in anon.post("/api/login", json={"password": PASSWORD}).text

    def test_repeated_failures_are_throttled(self, settings):
        settings.login_max_failures = 3
        client = TestClient(create_app(settings))
        for _ in range(3):
            client.post("/api/login", json={"password": "wrong"})
        response = client.post("/api/login", json={"password": "wrong"})
        assert response.status_code == 429
        assert "Retry-After" in response.headers

    def test_throttle_blocks_even_the_right_password(self, settings):
        # Otherwise the lockout would be trivially bypassed by a lucky guess.
        settings.login_max_failures = 2
        client = TestClient(create_app(settings))
        for _ in range(2):
            client.post("/api/login", json={"password": "wrong"})
        assert client.post("/api/login", json={"password": PASSWORD}).status_code == 429


class TestTokenGate:
    def test_game_routes_reject_a_missing_token(self, anon):
        assert anon.post("/api/games").status_code == 401
        assert anon.get("/api/games/whatever").status_code == 401
        assert anon.get("/api/session").status_code == 401

    def test_rejects_a_forged_token(self, anon):
        anon.headers["Authorization"] = "Bearer not-a-real-token"
        assert anon.post("/api/games").status_code == 401

    def test_rejects_a_token_signed_with_another_key(self, anon):
        anon.headers["Authorization"] = f"Bearer {issue_token('a-different-secret-key')}"
        assert anon.post("/api/games").status_code == 401

    def test_rejects_a_malformed_authorization_header(self, anon, client):
        token = client.headers["Authorization"].removeprefix("Bearer ")
        for header in (token, f"Basic {token}", "Bearer", "Bearer "):
            anon.headers["Authorization"] = header
            assert anon.post("/api/games").status_code == 401

    def test_rejects_an_expired_token(self, settings):
        settings.token_max_age = 60
        client = TestClient(create_app(settings))
        client.headers["Authorization"] = f"Bearer {obtain_token(client)}"
        assert client.post("/api/games").status_code == 201

        # itsdangerous stamps wall-clock time into the token.
        real_time = time.time
        try:
            time.time = lambda: real_time() + 61
            assert client.post("/api/games").status_code == 401
        finally:
            time.time = real_time

    def test_answers_with_a_bearer_challenge(self, anon):
        assert anon.post("/api/games").headers.get("WWW-Authenticate") == "Bearer"

    def test_session_check_accepts_a_valid_token(self, client):
        assert client.get("/api/session").json() == {"valid": True}


class TestCors:
    def test_allows_the_configured_frontend_origin(self, client):
        response = client.post("/api/games", headers={"Origin": ORIGIN})
        assert response.headers["access-control-allow-origin"] == ORIGIN

    def test_does_not_allow_an_unknown_origin(self, client):
        response = client.post("/api/games", headers={"Origin": "http://evil.example"})
        assert "access-control-allow-origin" not in response.headers

    def test_preflight_permits_the_authorization_header(self, anon):
        response = anon.options(
            "/api/games",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert response.status_code == 200
        assert "authorization" in response.headers["access-control-allow-headers"].lower()


class TestNewGame:
    def test_returns_an_empty_board(self, client):
        board = new_game(client)
        assert board["attempts"] == []
        assert board["attempts_remaining"] == 5
        assert board["max_attempts"] == 5
        assert board["word_length"] == 5
        assert board["is_over"] is False
        assert board["is_won"] is False
        assert board["letter_states"] == {}

    def test_does_not_reveal_the_answer(self, client):
        assert new_game(client)["answer"] is None

    def test_each_game_gets_its_own_id(self, client):
        assert new_game(client)["game_id"] != new_game(client)["game_id"]

    def test_game_id_is_not_guessable(self, client):
        # Sequential ids would let one player read another player's board.
        assert len(new_game(client)["game_id"]) >= 16


class TestGuessing:
    def test_scores_a_guess(self, client, answer):
        answer("crane")
        board = new_game(client)
        result = guess(client, board["game_id"], "state").json()
        assert result["attempts"][0]["guess"] == "state"
        assert result["attempts"][0]["colours"] == ["miss", "miss", "hit", "miss", "hit"]
        assert result["attempts_remaining"] == 4

    def test_accepts_uppercase(self, client, answer):
        answer("crane")
        board = new_game(client)
        assert guess(client, board["game_id"], "STATE").json()["attempts"][0]["guess"] == "state"

    def test_winning_ends_the_game_and_reveals_the_answer(self, client, answer):
        answer("crane")
        board = new_game(client)
        result = guess(client, board["game_id"], "crane").json()
        assert result["is_won"] is True
        assert result["is_over"] is True
        assert result["answer"] == "crane"

    def test_running_out_reveals_the_answer(self, settings):
        settings.max_attempts = 2
        client = authed(settings)
        client.app.state.repository.random_word = lambda rng=None: "crane"

        board = new_game(client)
        guess(client, board["game_id"], "state")
        result = guess(client, board["game_id"], "tasty").json()
        assert result["is_over"] is True
        assert result["is_won"] is False
        assert result["answer"] == "crane"

    def test_reports_keyboard_letter_states(self, client, answer):
        answer("crane")
        board = new_game(client)
        states = guess(client, board["game_id"], "state").json()["letter_states"]
        assert states == {"s": "miss", "t": "miss", "a": "hit", "e": "hit"}

    def test_rejects_a_word_outside_the_list(self, client):
        board = new_game(client)
        response = guess(client, board["game_id"], "zzzzz")
        assert response.status_code == 400
        assert response.json()["detail"] == "Not in word list"

    def test_rejects_the_wrong_length(self, client):
        response = guess(client, new_game(client)["game_id"], "cran")
        assert response.status_code == 400
        assert "5 letters" in response.json()["detail"]

    def test_rejects_non_letters(self, client):
        assert guess(client, new_game(client)["game_id"], "cr4ne").status_code == 400

    def test_a_rejected_guess_costs_nothing(self, client):
        game_id = new_game(client)["game_id"]
        guess(client, game_id, "zzzzz")
        assert client.get(f"/api/games/{game_id}").json()["attempts_remaining"] == 5

    def test_rejects_an_oversized_payload(self, client):
        assert guess(client, new_game(client)["game_id"], "z" * 500).status_code == 422

    def test_guessing_after_the_game_ends_conflicts(self, client, answer):
        answer("crane")
        game_id = new_game(client)["game_id"]
        guess(client, game_id, "crane")
        assert guess(client, game_id, "state").status_code == 409

    def test_unknown_game_is_not_found(self, client):
        assert guess(client, "no-such-game", "crane").status_code == 404


class TestReadGame:
    def test_returns_the_board_so_a_reload_can_resume(self, client, answer):
        answer("crane")
        game_id = new_game(client)["game_id"]
        guess(client, game_id, "state")

        board = client.get(f"/api/games/{game_id}").json()
        assert board["game_id"] == game_id
        assert [a["guess"] for a in board["attempts"]] == ["state"]
        assert board["answer"] is None

    def test_unknown_game_is_not_found(self, client):
        assert client.get("/api/games/no-such-game").status_code == 404

    def test_expired_game_is_not_found(self, client):
        game_id = new_game(client)["game_id"]
        client.app.state.store.delete(game_id)
        assert client.get(f"/api/games/{game_id}").status_code == 404
