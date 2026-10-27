"""End-to-end tests over the HTTP surface: accounts, then the game."""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import ANSWERS, EXTRA_GUESSES, ORIGIN, write_length
from wordle.accounts import SignInDisabled
from wordle.app import create_app


def new_game(client) -> dict:
    response = client.post("/api/games")
    assert response.status_code == 201
    return response.json()


def guess(client, game_id: str, word: str):
    return client.post(f"/api/games/{game_id}/guesses", json={"guess": word})


class TestServesJsonOnly:
    """The frontend is a separate application. This one hands out no pages."""

    def test_serves_no_html_pages(self, client):
        for path in ("/", "/login", "/index.html"):
            assert client.get(path).status_code == 404

    def test_serves_no_static_assets(self, client):
        for path in ("/static/app.js", "/static/style.css", "/app.js"):
            assert client.get(path).status_code == 404

    def test_health_check_is_public(self, client):
        assert client.get("/healthz").json() == {"status": "ok"}

    def test_api_docs_are_not_exposed(self, client):
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404


class TestAnonymousPlay:
    """No account needed: the game plays exactly as it did before accounts."""

    def test_a_game_can_be_played_without_signing_in(self, client, answer):
        answer("crane")
        game = new_game(client)
        assert guess(client, game["game_id"], "crane").json()["is_won"] is True

    def test_there_is_no_shared_password_any_more(self, client):
        assert client.post("/api/login", json={"password": "x"}).status_code == 404

    def test_an_anonymous_game_is_open_to_anyone_holding_its_id(self, client, sign_in):
        # As before accounts: the unguessable id is the only key.
        game_id = new_game(client)["game_id"]
        assert sign_in("someone").get(f"/api/games/{game_id}").status_code == 200

    def test_a_signed_in_player_can_finish_a_game_started_anonymously(
        self, client, sign_in, answer
    ):
        answer("crane")
        game_id = new_game(client)["game_id"]
        player = sign_in("someone")
        assert guess(player, game_id, "crane").json()["is_won"] is True


class TestSignIn:
    def test_me_needs_a_token(self, client):
        response = client.get("/api/players/me")
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_first_sign_in_creates_the_player(self, sign_in, players):
        response = sign_in("google|1", email="ada@example.com", verified=True, name="Ada").get(
            "/api/players/me"
        )
        assert response.status_code == 200
        assert response.json()["display_name"] == "Ada"
        assert len(players) == 1

    def test_signing_in_again_is_the_same_player(self, sign_in, players):
        first = sign_in("google|1").get("/api/players/me").json()
        again = sign_in("google|1").get("/api/players/me").json()
        assert first == again
        assert len(players) == 1

    def test_a_known_player_costs_no_call_to_the_provider(self, sign_in, provider):
        player = sign_in("google|1")
        player.get("/api/players/me")
        player.get("/api/players/me")
        player.post("/api/games")
        assert provider.profile_calls == 1

    def test_a_bad_token_is_refused_not_treated_as_anonymous(self, client):
        client.headers["Authorization"] = "Bearer not-a-real-token"
        response = client.post("/api/games")
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"

    @pytest.mark.parametrize("header", ["token", "Basic abc", "Bearer", "Bearer "])
    def test_a_malformed_authorization_header_is_refused(self, client, header):
        client.headers["Authorization"] = header
        assert client.post("/api/games").status_code == 401

    def test_a_provider_outage_is_a_503_not_a_401(self, sign_in, provider):
        player = sign_in("google|1")
        provider.down = True
        assert player.get("/api/players/me").status_code == 503

    def test_a_provider_outage_does_not_stop_anonymous_play(self, client, provider):
        provider.down = True
        assert client.post("/api/games").status_code == 201

    def test_with_sign_in_off_tokens_are_refused_and_play_still_works(self, settings):
        app = create_app(settings, accounts=SignInDisabled())
        try:
            client = TestClient(app)
            assert client.post("/api/games").status_code == 201
            client.headers["Authorization"] = "Bearer anything"
            response = client.get("/api/players/me")
            assert response.status_code == 401
            assert "not enabled" in response.json()["detail"]
        finally:
            app.state.store.close()


class TestDeletePlayer:
    def test_deleting_needs_a_token(self, client):
        assert client.delete("/api/players/me").status_code == 401

    def test_deletes_the_player_and_their_games(self, sign_in, players, app):
        player = sign_in("google|1")
        me = player.get("/api/players/me").json()["player_id"]
        game_id = new_game(player)["game_id"]

        assert player.delete("/api/players/me").status_code == 204
        assert len(players) == 0
        assert app.state.store.get(game_id, viewer=me) is None

    def test_other_players_and_anonymous_games_are_untouched(self, sign_in, client, players):
        keep = sign_in("github|2")
        their_game = new_game(keep)["game_id"]
        anonymous_game = new_game(client)["game_id"]

        sign_in("google|1").delete("/api/players/me")
        assert len(players) == 1
        assert keep.get(f"/api/games/{their_game}").status_code == 200
        assert client.get(f"/api/games/{anonymous_game}").status_code == 200

    def test_the_old_token_is_refused_afterwards(self, sign_in):
        player = sign_in("google|1")
        player.get("/api/players/me")
        player.delete("/api/players/me")

        response = player.get("/api/players/me")
        assert response.status_code == 401
        assert "deleted" in response.json()["detail"]

    def test_signing_in_again_is_a_new_empty_player(self, sign_in):
        player = sign_in("google|1")
        before = player.get("/api/players/me").json()["player_id"]
        game_id = new_game(player)["game_id"]
        player.delete("/api/players/me")

        again = sign_in("google|1")
        assert again.get("/api/players/me").json()["player_id"] != before
        assert again.get(f"/api/games/{game_id}").status_code == 404

    def test_the_provider_account_is_closed(self, sign_in, provider):
        sign_in("google|1").delete("/api/players/me")
        assert [i.subject for i in provider.deleted] == ["google|1"]

    def test_a_provider_outage_deletes_nothing(self, sign_in, provider):
        player = sign_in("google|1")
        player.get("/api/players/me")
        game_id = new_game(player)["game_id"]
        provider.delete_fails = True
        assert player.delete("/api/players/me").status_code == 503
        assert player.get(f"/api/games/{game_id}").status_code == 200

    def test_a_database_outage_deletes_nothing(self, sign_in, players, app, monkeypatch):
        from wordle.accounts import AccountsUnavailable

        player = sign_in("google|1")
        player.get("/api/players/me")
        game_id = new_game(player)["game_id"]

        def down(*args, **kwargs):
            raise AccountsUnavailable("down")

        monkeypatch.setattr(players, "delete", down)
        assert player.delete("/api/players/me").status_code == 503
        assert player.get(f"/api/games/{game_id}").status_code == 200

    def test_browsers_may_send_delete(self, client):
        response = client.options(
            "/api/players/me",
            headers={"Origin": ORIGIN, "Access-Control-Request-Method": "DELETE"},
        )
        assert response.status_code == 200
        assert "DELETE" in response.headers["access-control-allow-methods"]


class TestGameOwnership:
    def test_a_signed_in_players_game_is_theirs(self, sign_in, answer):
        answer("crane")
        player = sign_in("google|1")
        game_id = new_game(player)["game_id"]
        assert player.get(f"/api/games/{game_id}").status_code == 200
        assert guess(player, game_id, "crane").status_code == 200

    def test_another_player_cannot_see_it(self, sign_in):
        game_id = new_game(sign_in("google|1"))["game_id"]
        other = sign_in("github|2")
        assert other.get(f"/api/games/{game_id}").status_code == 404
        assert other.post(f"/api/games/{game_id}/start").status_code == 404
        assert guess(other, game_id, "crane").status_code == 404

    def test_an_anonymous_player_cannot_see_it(self, sign_in, client):
        game_id = new_game(sign_in("google|1"))["game_id"]
        assert client.get(f"/api/games/{game_id}").status_code == 404

    def test_someone_elses_game_looks_like_no_game(self, sign_in):
        game_id = new_game(sign_in("google|1"))["game_id"]
        other = sign_in("github|2")
        assert (
            other.get(f"/api/games/{game_id}").json() == other.get("/api/games/no-such-game").json()
        )

    def test_the_same_person_on_another_sign_in_method_keeps_their_games(self, sign_in):
        google = sign_in("google|1", email="ada@example.com", verified=True)
        game_id = new_game(google)["game_id"]
        github = sign_in("github|2", email="ADA@example.com", verified=True)
        assert github.get(f"/api/games/{game_id}").status_code == 200


class TestCors:
    def test_allows_the_configured_frontend_origin(self, client):
        response = client.post("/api/games", headers={"Origin": ORIGIN})
        assert response.headers["access-control-allow-origin"] == ORIGIN

    def test_does_not_allow_an_unknown_origin(self, client):
        response = client.post("/api/games", headers={"Origin": "http://evil.example"})
        assert "access-control-allow-origin" not in response.headers

    def test_preflight_permits_the_authorization_header(self, client):
        response = client.options(
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

    def test_running_out_reveals_the_answer(self, settings, make_client):
        client = make_client(settings)
        client.app.state.catalogue.answers().random_word = lambda rng=None: "crane"

        # Two attempts, asked for, so the board runs out in two guesses.
        board = client.post("/api/games", json={"max_attempts": 2}).json()
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

    def test_rejects_something_that_is_not_a_word(self, client):
        response = guess(client, new_game(client)["game_id"], "zzzzz")
        assert response.status_code == 400
        assert response.json()["detail"] == "Enter a valid word"

    def test_accepts_a_real_word_that_is_never_an_answer(self, client, answer):
        # Guesses come from the dictionary, which is far larger than the
        # answer list. Rejecting real words is the bug this guards.
        answer("crane")
        board = new_game(client)
        result = guess(client, board["game_id"], "recan").json()
        assert result["attempts"][0]["guess"] == "recan"
        assert result["attempts"][0]["colours"] == ["present"] * 5
        assert result["attempts_remaining"] == 4

    def test_rejects_the_wrong_length(self, client):
        response = guess(client, new_game(client)["game_id"], "cran")
        assert response.status_code == 400
        assert "5 letters" in response.json()["detail"]

    def test_rejects_non_letters(self, client):
        assert guess(client, new_game(client)["game_id"], "cr4ne").status_code == 400

    def test_a_rejected_guess_costs_nothing(self, client):
        game_id = new_game(client)["game_id"]
        for bad in ("cran", "cr4ne", "zzzzz"):
            guess(client, game_id, bad)
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


class TestMultipleWordLengths:
    """Two players on different lengths at the same time, against one server."""

    def two_lengths(self, settings, tmp_path):
        """A deployment with both a 4- and a 5-letter list installed."""
        root = write_length(tmp_path / "multi", 5, ANSWERS, EXTRA_GUESSES)
        write_length(root, 4, ["cats", "dogs"], ["rats", "cobs"])
        return settings.model_copy(update={"word_lists_dir": root})

    def test_a_game_can_be_asked_for_by_length(self, settings, tmp_path, make_client):
        client = make_client(self.two_lengths(settings, tmp_path))
        response = client.post("/api/games", json={"word_length": 4})
        assert response.status_code == 201
        assert response.json()["word_length"] == 4

    def test_no_body_uses_the_default_length(self, settings, tmp_path, make_client):
        client = make_client(self.two_lengths(settings, tmp_path))
        assert client.post("/api/games").json()["word_length"] == 5

    def test_two_lengths_are_playable_at_once(self, settings, tmp_path, make_client):
        client = make_client(self.two_lengths(settings, tmp_path))
        four = client.post("/api/games", json={"word_length": 4}).json()["game_id"]
        five = client.post("/api/games", json={"word_length": 5}).json()["game_id"]

        # Each game accepts only guesses of its own length, and neither
        # disturbs the other.
        assert client.post(f"/api/games/{four}/guesses", json={"guess": "rats"}).status_code == 200
        assert client.post(f"/api/games/{five}/guesses", json={"guess": "cards"}).status_code == 200
        assert client.post(f"/api/games/{four}/guesses", json={"guess": "cards"}).status_code == 400
        assert client.post(f"/api/games/{five}/guesses", json={"guess": "rats"}).status_code == 400

        assert client.get(f"/api/games/{four}").json()["word_length"] == 4
        assert client.get(f"/api/games/{five}").json()["word_length"] == 5

    def test_an_uninstalled_length_is_refused(self, settings, tmp_path, make_client):
        client = make_client(self.two_lengths(settings, tmp_path))
        response = client.post("/api/games", json={"word_length": 9})
        assert response.status_code == 400
        assert "4, 5" in response.json()["detail"]

    def test_a_resumed_game_keeps_its_own_vocabulary(self, settings, tmp_path, make_client):
        """The store rehydrates by the target's length, not a process-wide list."""
        client = make_client(self.two_lengths(settings, tmp_path))
        four = client.post("/api/games", json={"word_length": 4}).json()["game_id"]
        client.post(f"/api/games/{four}/guesses", json={"guess": "rats"})

        resumed = client.get(f"/api/games/{four}").json()
        assert resumed["word_length"] == 4
        assert [a["guess"] for a in resumed["attempts"]] == ["rats"]


class TestAttemptCount:
    """A game can be asked for with its own attempt count."""

    def test_a_game_can_be_asked_for_by_attempt_count(self, client):
        response = client.post("/api/games", json={"max_attempts": 3})
        assert response.status_code == 201
        body = response.json()
        assert body["max_attempts"] == 3
        assert body["attempts_remaining"] == 3

    def test_no_body_derives_the_count_from_the_word(self, client):
        body = client.post("/api/games").json()
        assert body["max_attempts"] == body["word_length"] == 5

    def test_the_requested_count_is_what_actually_ends_the_game(self, client, answer):
        answer("crane")
        game_id = client.post("/api/games", json={"max_attempts": 2}).json()["game_id"]
        for _ in range(2):
            body = client.post(f"/api/games/{game_id}/guesses", json={"guess": "state"}).json()
        assert body["is_over"] is True
        assert body["is_won"] is False
        assert body["answer"] == "crane"

    def test_an_unwinnable_count_is_refused(self, client):
        # No client gets to hand itself infinite guesses. The upper bound
        # depends on the word, so the game refuses it (400) rather than the
        # schema (422).
        assert client.post("/api/games", json={"max_attempts": 500}).status_code == 400
        assert client.post("/api/games", json={"max_attempts": 0}).status_code == 422

    def two_lengths(self, settings, tmp_path):
        root = write_length(tmp_path / "multi", 5, ANSWERS, EXTRA_GUESSES)
        write_length(root, 4, ["cats", "dogs"], ["rats"])
        return settings.model_copy(update={"word_lists_dir": root})

    def test_the_default_count_follows_the_requested_length(self, settings, tmp_path, make_client):
        client = make_client(self.two_lengths(settings, tmp_path))
        for length in (4, 5):
            body = client.post("/api/games", json={"word_length": length}).json()
            assert (body["word_length"], body["max_attempts"]) == (length, length)

    def test_the_limit_follows_the_requested_length(self, settings, tmp_path, make_client):
        client = make_client(self.two_lengths(settings, tmp_path))
        # Six attempts is the ceiling at four letters and ordinary at five.
        assert (
            client.post("/api/games", json={"word_length": 4, "max_attempts": 6}).status_code == 201
        )
        assert (
            client.post("/api/games", json={"word_length": 5, "max_attempts": 6}).status_code == 201
        )

        refused = client.post("/api/games", json={"word_length": 4, "max_attempts": 7})
        assert refused.status_code == 400
        assert "4-letter" in refused.json()["detail"]

    def test_the_count_survives_a_resume(self, client):
        game_id = client.post("/api/games", json={"max_attempts": 3}).json()["game_id"]
        assert client.get(f"/api/games/{game_id}").json()["max_attempts"] == 3


class TestDomainLimitsReachTheClient:
    """The game's own limits decide, and the route answers for them."""

    def test_an_out_of_range_count_never_becomes_a_server_error(self, settings, make_client):
        # The schema bounds this field too, so the route's guard is belt and
        # braces -- but a rejected count must never read as a 5xx.
        client = make_client(settings)
        for count in (0, -1, 500):
            status = client.post("/api/games", json={"max_attempts": count}).status_code
            assert status < 500, count

    def test_zero_is_refused_rather_than_silently_defaulted(self, settings, make_client):
        client = make_client(settings)
        assert client.post("/api/games", json={"max_attempts": 0}).status_code == 422


class TestScoring:
    """The score rides along on the board, so no extra round trip is needed."""

    def test_a_game_in_progress_carries_no_score(self, client, answer):
        answer("crane")
        game = new_game(client)
        assert game["score"] is None
        assert guess(client, game["game_id"], "state").json()["score"] is None

    def test_a_finished_game_carries_its_score_and_its_working(self, client, answer):
        word = answer("crane")
        game = new_game(client)
        client.post(f"/api/games/{game['game_id']}/start")
        guess(client, game["game_id"], "state")
        score = guess(client, game["game_id"], word).json()["score"]

        assert score["is_won"] is True
        assert score["winning_attempt"] == 2
        assert score["word_length"] == 5
        assert score["max_attempts"] == 5
        # Played in no time at all, so very nearly the perfect 10.
        assert 9.9 < score["score"] <= 10.0
        assert score["multiplier"] == 1.0

    def test_a_lost_game_scores_zero(self, client, answer):
        answer("crane")
        game = new_game(client)
        for _ in range(5):
            response = guess(client, game["game_id"], "state")
        score = response.json()["score"]
        assert score["is_won"] is False
        assert score["score"] == 0.0

    def test_the_clock_starts_on_demand_and_survives_a_reload(self, client, answer):
        answer("crane")
        game = new_game(client)
        started = client.post(f"/api/games/{game['game_id']}/start")
        assert started.status_code == 200

        reloaded = client.get(f"/api/games/{game['game_id']}")
        assert reloaded.json()["score"] is None  # still playing

        guess(client, game["game_id"], "crane")
        score = client.get(f"/api/games/{game['game_id']}").json()["score"]
        assert score["game_time_seconds"] < 60

    def test_starting_an_unknown_game_is_a_404(self, client):
        assert client.post("/api/games/nope/start").status_code == 404
