"""Auth0Provider, with Auth0's HTTP answers faked. Sign-in is OidcProvider's
job and tested there; these tests cover closing accounts."""

from __future__ import annotations

import pytest

from wordle.accounts import AccountsUnavailable, Identity
from wordle.accounts.auth0 import TOKEN_MARGIN_SECONDS, Auth0Provider

ISSUER = "https://wordle-test.us.auth0.com/"
TOKEN_URL = "https://wordle-test.us.auth0.com/oauth/token"
USERS_URL = "https://wordle-test.us.auth0.com/api/v2/users/"


class FakeAuth0:
    """Answers token and delete requests, and records what was asked."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict, dict | None]] = []
        self.delete_status = 204
        self.token_status = 200
        self.tokens_issued = 0
        self.reject_token_once = False

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        if url == TOKEN_URL:
            if self.token_status != 200:
                return self.token_status, {"error": "access_denied"}
            self.tokens_issued += 1
            return 200, {"access_token": f"m2m-{self.tokens_issued}", "expires_in": 86400}
        if method == "DELETE":
            if self.reject_token_once:
                self.reject_token_once = False
                return 401, None
            return self.delete_status, None
        raise AssertionError(f"unexpected {method} {url}")

    def deletes(self):
        return [
            (url, headers["Authorization"])
            for method, url, headers, _ in self.calls
            if method == "DELETE"
        ]


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def auth0():
    return FakeAuth0()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def provider(auth0, clock):
    return Auth0Provider(
        ISSUER, "https://wordle-api", "client-id", "client-secret", request=auth0, clock=clock
    )


def test_deletes_the_user_by_their_id(provider, auth0):
    assert provider.delete_account(Identity(ISSUER, "google-oauth2|1029")) is True
    # The "|" in an Auth0 user id must be escaped in the URL.
    assert auth0.deletes() == [(USERS_URL + "google-oauth2%7C1029", "Bearer m2m-1")]


def test_asks_for_a_management_token_with_client_credentials(provider, auth0):
    provider.delete_account(Identity(ISSUER, "auth0|1"))
    method, url, _, body = auth0.calls[0]
    assert (method, url) == ("POST", TOKEN_URL)
    assert body == {
        "grant_type": "client_credentials",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "audience": "https://wordle-test.us.auth0.com/api/v2/",
    }


def test_reuses_the_management_token_until_it_nearly_expires(provider, auth0, clock):
    provider.delete_account(Identity(ISSUER, "auth0|1"))
    provider.delete_account(Identity(ISSUER, "auth0|2"))
    assert auth0.tokens_issued == 1

    clock.now += 86400 - TOKEN_MARGIN_SECONDS + 1
    provider.delete_account(Identity(ISSUER, "auth0|3"))
    assert auth0.tokens_issued == 2


def test_a_rejected_token_is_renewed_once(provider, auth0):
    provider.delete_account(Identity(ISSUER, "auth0|1"))
    auth0.reject_token_once = True
    assert provider.delete_account(Identity(ISSUER, "auth0|2")) is True
    assert auth0.deletes()[-1][1] == "Bearer m2m-2"


def test_an_account_already_gone_counts_as_deleted(provider, auth0):
    auth0.delete_status = 404
    assert provider.delete_account(Identity(ISSUER, "auth0|1")) is True


@pytest.mark.parametrize("status", [400, 403, 429, 500, 503])
def test_any_other_answer_is_a_failure(provider, auth0, status):
    auth0.delete_status = status
    with pytest.raises(AccountsUnavailable):
        provider.delete_account(Identity(ISSUER, "auth0|1"))


def test_wrong_credentials_are_a_failure(provider, auth0):
    auth0.token_status = 401
    with pytest.raises(AccountsUnavailable, match="credentials"):
        provider.delete_account(Identity(ISSUER, "auth0|1"))
    assert auth0.deletes() == []


def test_an_identity_from_another_provider_is_left_alone(provider, auth0):
    assert provider.delete_account(Identity("https://old-provider.test/", "x")) is False
    assert auth0.calls == []


class TestHttpRequest:
    """The real network function, against a local server instead of Auth0."""

    @pytest.fixture
    def server(self):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        seen = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers["Content-Length"])
                seen["body"] = json.loads(self.rfile.read(length))
                seen["content_type"] = self.headers["Content-Type"]
                payload = json.dumps({"access_token": "t", "expires_in": 60}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_DELETE(self):
                seen["authorization"] = self.headers["Authorization"]
                self.send_response(404 if "gone" in self.path else 204)
                self.send_header("Content-Length", "0")
                self.end_headers()

        httpd = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{httpd.server_port}", seen
        httpd.shutdown()
        httpd.server_close()

    def test_posts_json_and_reads_json(self, server):
        from wordle.accounts.auth0 import http_request

        base, seen = server
        status, body = http_request("POST", base + "/oauth/token", {}, {"a": 1})
        assert (status, body) == (200, {"access_token": "t", "expires_in": 60})
        assert seen["body"] == {"a": 1}
        assert seen["content_type"] == "application/json"

    def test_returns_error_statuses_instead_of_raising(self, server):
        from wordle.accounts.auth0 import http_request

        base, seen = server
        assert (
            http_request("DELETE", base + "/users/x", {"Authorization": "Bearer t"}, None)[0] == 204
        )
        assert seen["authorization"] == "Bearer t"
        assert http_request("DELETE", base + "/users/gone", {}, None)[0] == 404

    def test_an_unreachable_server_is_unavailable(self):
        from wordle.accounts.auth0 import http_request

        with pytest.raises(AccountsUnavailable):
            http_request("DELETE", "http://127.0.0.1:9/users/x", {}, None)
