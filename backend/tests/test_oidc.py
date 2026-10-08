"""The OpenID Connect adapter, against a provider faked down to its HTTP answers.

Real keys, real signatures: only the network is replaced. What these tests pin
is that a token is accepted only when every check passes.
"""

from __future__ import annotations

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from wordle.accounts import AccountsUnavailable, AuthenticationError, Identity
from wordle.accounts.oidc import KEY_REFRESH_INTERVAL, OidcProvider

ISSUER = "https://tenant.example-idp.test/"
AUDIENCE = "https://wordle-api"
DISCOVERY = ISSUER.rstrip("/") + "/.well-known/openid-configuration"
JWKS_URI = ISSUER + ".well-known/jwks.json"
USERINFO = ISSUER + "userinfo"


def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def public_jwk(private, kid: str) -> dict:
    jwk = json.loads(RSAAlgorithm.to_jwk(private.public_key()))
    return {**jwk, "kid": kid, "use": "sig", "alg": "RS256"}


class FakeIdp:
    """The three documents an OIDC provider serves, and a request log."""

    def __init__(self):
        self.key = rsa_key()
        self.keys = [public_jwk(self.key, "key-1")]
        self.userinfo: dict = {"sub": "auth0|1", "email": "ada@example.com"}
        self.discovery = {"issuer": ISSUER, "jwks_uri": JWKS_URI, "userinfo_endpoint": USERINFO}
        self.requests: list[str] = []
        self.down = False

    def fetch(self, url, headers):
        self.requests.append(url)
        if self.down:
            raise AccountsUnavailable("down")
        if url == DISCOVERY:
            return self.discovery
        if url == JWKS_URI:
            return {"keys": self.keys}
        if url == USERINFO:
            assert headers["Authorization"].startswith("Bearer ")
            return self.userinfo
        raise AssertionError(f"unexpected fetch {url}")

    def token(self, *, key=None, kid="key-1", alg="RS256", **overrides) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "auth0|1",
            "iat": now,
            "exp": now + 600,
            **overrides,
        }
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, key or self.key, algorithm=alg, headers={"kid": kid})


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def idp():
    return FakeIdp()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def provider(idp, clock):
    return OidcProvider(ISSUER, AUDIENCE, fetch=idp.fetch, clock=clock)


class TestVerify:
    def test_a_good_token_names_its_owner(self, provider, idp):
        assert provider.verify(idp.token()) == Identity(ISSUER, "auth0|1")

    def test_keys_are_fetched_once_then_cached(self, provider, idp):
        provider.verify(idp.token())
        provider.verify(idp.token())
        assert idp.requests == [DISCOVERY, JWKS_URI]

    @pytest.mark.parametrize(
        "claims",
        [
            {"aud": "https://someone-else"},
            {"iss": "https://evil.test/"},
            {"exp": int(time.time()) - 3600},
            {"exp": None},
            {"sub": None},
            {"iat": None},
            {"aud": None},
        ],
        ids=["wrong-aud", "wrong-iss", "expired", "no-exp", "no-sub", "no-iat", "no-aud"],
    )
    def test_a_token_failing_any_check_is_refused(self, provider, idp, claims):
        with pytest.raises(AuthenticationError):
            provider.verify(idp.token(**claims))

    def test_a_token_signed_by_another_key_is_refused(self, provider, idp):
        with pytest.raises(AuthenticationError):
            provider.verify(idp.token(key=rsa_key()))

    def test_an_unsigned_token_is_refused(self, provider, idp):
        token = jwt.encode({"sub": "x"}, None, algorithm="none", headers={"kid": "key-1"})
        with pytest.raises(AuthenticationError):
            provider.verify(token)

    def test_an_hmac_token_using_the_public_key_as_secret_is_refused(self, provider, idp):
        # The classic algorithm-confusion attack.
        token = jwt.encode(
            {"sub": "x", "iss": ISSUER, "aud": AUDIENCE},
            "public-key-material-padded-to-32-bytes",
            algorithm="HS256",
            headers={"kid": "key-1"},
        )
        with pytest.raises(AuthenticationError):
            provider.verify(token)

    def test_garbage_is_refused(self, provider):
        with pytest.raises(AuthenticationError):
            provider.verify("not.a.jwt")

    def test_a_token_naming_no_key_is_refused(self, provider, idp):
        with pytest.raises(AuthenticationError):
            provider.verify(idp.token(kid=""))

    def test_a_rotated_key_is_picked_up(self, provider, idp, clock):
        provider.verify(idp.token())
        new = rsa_key()
        idp.keys.append(public_jwk(new, "key-2"))
        clock.now += KEY_REFRESH_INTERVAL + 1
        assert provider.verify(idp.token(key=new, kid="key-2")).subject == "auth0|1"

    def test_unknown_keys_cannot_hammer_the_provider(self, provider, idp):
        provider.verify(idp.token())
        for _ in range(20):
            with pytest.raises(AuthenticationError):
                provider.verify(idp.token(key=rsa_key(), kid="made-up"))
        assert idp.requests.count(JWKS_URI) == 1

    def test_a_provider_outage_is_unavailable(self, provider, idp):
        idp.down = True
        with pytest.raises(AccountsUnavailable):
            provider.verify(idp.token())

    def test_a_discovery_document_for_another_issuer_is_refused(self, provider, idp):
        idp.discovery["issuer"] = ISSUER.rstrip("/")  # the classic missing slash
        with pytest.raises(AccountsUnavailable):
            provider.verify(idp.token())

    def test_other_asymmetric_algorithms_can_be_allowed(self, idp, clock):
        key = ec.generate_private_key(ec.SECP256R1())
        jwk = json.loads(ECAlgorithm.to_jwk(key.public_key()))
        idp.keys = [{**jwk, "kid": "ec-1", "use": "sig", "alg": "ES256"}]
        provider = OidcProvider(ISSUER, AUDIENCE, algorithms=["ES256"], fetch=idp.fetch)
        assert provider.verify(idp.token(key=key, kid="ec-1", alg="ES256")).subject == "auth0|1"

    def test_symmetric_algorithms_cannot_be_configured(self):
        with pytest.raises(ValueError):
            OidcProvider(ISSUER, AUDIENCE, algorithms=["HS256"])


class TestProfile:
    def test_reads_the_standard_claims(self, provider, idp):
        idp.userinfo = {"email": "ada@example.com", "email_verified": True, "name": "Ada"}
        profile = provider.profile(idp.token())
        assert (profile.email, profile.email_verified, profile.name) == (
            "ada@example.com",
            True,
            "Ada",
        )

    def test_a_missing_email_is_fine(self, provider, idp):
        idp.userinfo = {"sub": "github|1", "nickname": "ada"}
        profile = provider.profile(idp.token())
        assert profile.email is None
        assert profile.name == "ada"

    @pytest.mark.parametrize("value", [False, "false", "yes", 1, None])
    def test_only_a_clear_yes_counts_as_verified(self, provider, idp, value):
        idp.userinfo = {"email": "ada@example.com", "email_verified": value}
        assert provider.profile(idp.token()).email_verified is False

    def test_the_string_true_counts_as_verified(self, provider, idp):
        idp.userinfo = {"email": "ada@example.com", "email_verified": "true"}
        assert provider.profile(idp.token()).email_verified is True

    def test_an_absurdly_long_email_is_ignored(self, provider, idp):
        idp.userinfo = {"email": "a" * 400 + "@example.com", "email_verified": True}
        assert provider.profile(idp.token()).email is None
