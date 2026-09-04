"""End-to-end tests over the HTTP surface: the gate, then the game."""

from tests.conftest import PASSWORD, login


def new_game(client) -> dict:
    response = client.post("/api/games")
    assert response.status_code == 201
    return response.json()


def guess(client, game_id: str, word: str):
    return client.post(f"/api/games/{game_id}/guesses", json={"guess": word})


class TestAccessControl:
    def test_health_check_is_public(self, anon):
        assert anon.get("/healthz").json() == {"status": "ok"}

    def test_root_redirects_anonymous_visitors_to_login(self, anon):
        response = anon.get("/", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_login_page_is_public(self, anon):
        response = anon.get("/login")
        assert response.status_code == 200
        assert "password" in response.text.lower()

    def test_api_rejects_anonymous_requests(self, anon):
        assert anon.post("/api/games").status_code == 401
        assert anon.get("/api/games/whatever").status_code == 401

    def test_static_assets_need_a_session(self, anon):
        # The whole site is private, scripts and styles included.
        assert anon.get("/static/app.js").status_code == 401
        assert anon.get("/static/style.css").status_code == 401

    def test_wrong_password_is_rejected(self, anon):
        response = anon.post("/login", data={"password": "guess"}, follow_redirects=False)
        assert response.status_code == 401
        assert "wrong password" in response.text.lower()

    def test_empty_password_is_rejected(self, anon):
        assert anon.post("/login", data={"password": ""}).status_code == 401

    def test_correct_password_starts_a_session(self, anon):
        response = anon.post("/login", data={"password": PASSWORD}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert "session" in response.cookies

    def test_session_unlocks_the_page_and_its_assets(self, client):
        assert client.get("/").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/static/style.css").status_code == 200

    def test_login_page_redirects_an_authenticated_visitor(self, client):
        response = client.get("/login", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/"

    def test_logout_ends_the_session(self, client):
        client.post("/logout")
        assert client.get("/", follow_redirects=False).status_code == 303
        assert client.post("/api/games").status_code == 401

    def test_password_never_appears_in_served_files(self, client):
        for path in ("/", "/static/app.js", "/static/style.css"):
            assert PASSWORD not in client.get(path).text

    def test_static_route_refuses_path_traversal(self, client):
        for attempt in ("../backend/pyproject.toml", "....//pyproject.toml"):
            assert client.get(f"/static/{attempt}").status_code == 404

    def test_api_docs_are_not_exposed(self, anon):
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert anon.get(path).status_code == 404

    def test_repeated_failures_are_throttled(self, settings):
        settings.login_max_failures = 3
        client = login(settings)
        for _ in range(3):
            client.post("/login", data={"password": "wrong"})
        response = client.post("/login", data={"password": "wrong"})
        assert response.status_code == 429
        assert "Retry-After" in response.headers

    def test_throttle_blocks_even_the_right_password(self, settings):
        # Otherwise the lockout would be trivially bypassed by a lucky guess.
        settings.login_max_failures = 2
        client = login(settings)
        for _ in range(2):
            client.post("/login", data={"password": "wrong"})
        assert client.post("/login", data={"password": PASSWORD}).status_code == 429


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

    def test_running_out_reveals_the_answer(self, client, answer, settings):
        settings.max_attempts = 2
        client = login(settings)
        client.post("/login", data={"password": PASSWORD})
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
        response = guess(client, new_game(client)["game_id"], "cr4ne")
        assert response.status_code == 400

    def test_a_rejected_guess_costs_nothing(self, client):
        game_id = new_game(client)["game_id"]
        guess(client, game_id, "zzzzz")
        assert client.get(f"/api/games/{game_id}").json()["attempts_remaining"] == 5

    def test_rejects_an_oversized_payload(self, client):
        response = guess(client, new_game(client)["game_id"], "z" * 500)
        assert response.status_code == 422

    def test_guessing_after_the_game_ends_conflicts(self, client, answer):
        answer("crane")
        game_id = new_game(client)["game_id"]
        guess(client, game_id, "crane")
        response = guess(client, game_id, "state")
        assert response.status_code == 409

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

    def test_expired_game_is_not_found(self, client, settings):
        game_id = new_game(client)["game_id"]
        client.app.state.store.delete(game_id)
        assert client.get(f"/api/games/{game_id}").status_code == 404
