"""OpenID Connect identity provider. Standard OIDC only, no vendor code.

Configured with two values: the issuer URL and the audience (the identifier
this API is registered under at the provider). Everything else, where the
signing keys are and where to ask about a user, is read from the issuer's
discovery document at `<issuer>/.well-known/openid-configuration`.

Swapping provider means changing those two values. Sign-in methods (email and
password, Google, GitHub) are configured at the provider, not here: whichever
way someone signed in, this API receives the same kind of token.

OpenID Connect has no way to close an account, so this class cannot. A
provider-specific class (see auth0.py) wraps this one and adds that.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import jwt
from jwt import PyJWK, PyJWKSet

from .model import Credential, Identity, Profile
from .service import AccountsUnavailable, AuthenticationError

#: Seconds of clock difference forgiven between us and the provider.
DEFAULT_LEEWAY = 30
#: The least time between two key-set downloads. A token naming a key we do
#: not have triggers a refetch (the provider may have rotated), but a stream of
#: junk tokens must not turn into a stream of requests to the provider.
KEY_REFRESH_INTERVAL = 60.0
HTTP_TIMEOUT = 5.0
#: The longest email address the standards allow. Anything longer is ignored.
EMAIL_MAX = 320

#: Signature algorithms that are ever acceptable. Symmetric ones are excluded on
#: purpose: an HMAC key would have to be shared, and "none" is no signature.
_ASYMMETRIC = {
    *("RS256", "RS384", "RS512"),
    *("PS256", "PS384", "PS512"),
    *("ES256", "ES384", "ES512"),
    "EdDSA",
}

FetchJson = Callable[[str, Mapping[str, str]], Any]


def fetch_json(url: str, headers: Mapping[str, str]) -> Any:
    """GET a URL and parse JSON. Any failure is AccountsUnavailable."""
    request = urllib.request.Request(url, headers={"Accept": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            # Only the userinfo call carries the user's token, so this is the
            # provider rejecting it: a credentials problem, not an outage.
            raise AuthenticationError("The identity provider rejected the token") from exc
        raise AccountsUnavailable(f"Identity provider answered {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise AccountsUnavailable("Identity provider unreachable") from exc


class OidcProvider:
    """Verifies provider-issued JWT access tokens locally, against its public keys.

    Thread-safe. The discovery document and key set are fetched on first use
    and cached, so a provider outage at startup does not stop the game, and a
    verified token costs no network call.
    """

    def __init__(
        self,
        issuer: str,
        audience: str,
        *,
        algorithms: Sequence[str] = ("RS256",),
        leeway: int = DEFAULT_LEEWAY,
        fetch: FetchJson = fetch_json,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        unsafe = set(algorithms) - _ASYMMETRIC
        if unsafe or not algorithms:
            raise ValueError(f"Only asymmetric signature algorithms are allowed, not {unsafe}")
        self._issuer = issuer
        self._audience = audience
        self._algorithms = list(algorithms)
        self._leeway = leeway
        self._fetch = fetch
        self._clock = clock
        self._lock = threading.Lock()
        self._discovery: dict[str, Any] | None = None
        self._keys: dict[str, PyJWK] = {}
        self._keys_fetched_at: float | None = None

    # --- IdentityProvider ---------------------------------------------------

    @property
    def issuer(self) -> str:
        return self._issuer

    def verify(self, token: str) -> Credential:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthenticationError("Malformed token") from exc
        if header.get("alg") not in self._algorithms:
            raise AuthenticationError("Token signed with a disallowed algorithm")

        key = self._signing_key(header.get("kid"))
        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("Token expired") from exc
        except jwt.PyJWTError as exc:
            raise AuthenticationError("Invalid token") from exc

        subject = claims["sub"]
        if not isinstance(subject, str) or not subject:
            raise AuthenticationError("Invalid token")
        try:
            issued_at = float(claims["iat"])
        except (TypeError, ValueError) as exc:
            raise AuthenticationError("Invalid token") from exc
        return Credential(Identity(issuer=self._issuer, subject=subject), issued_at)

    def profile(self, token: str) -> Profile:
        endpoint = self._discovered("userinfo_endpoint")
        info = self._fetch(endpoint, {"Authorization": f"Bearer {token}"})
        if not isinstance(info, dict):
            raise AccountsUnavailable("Identity provider sent an unreadable profile")
        email = info.get("email")
        verified = info.get("email_verified")
        if not isinstance(email, str) or not email or len(email) > EMAIL_MAX:
            email = None
        name = info.get("name") or info.get("nickname") or info.get("preferred_username")
        return Profile(
            email=email,
            # Some providers send the string "true". Anything else is not a yes;
            # `is True`, because 1 == True and 1 is not a yes.
            email_verified=verified is True or verified == "true",
            name=name if isinstance(name, str) else None,
        )

    def delete_account(self, identity: Identity) -> bool:
        """Always False: the standard gives no way to close an account."""
        return False

    # --- Discovery and keys -------------------------------------------------

    def _discovered(self, field: str) -> str:
        with self._lock:
            if self._discovery is None:
                url = self._issuer.rstrip("/") + "/.well-known/openid-configuration"
                document = self._fetch(url, {})
                if not isinstance(document, dict) or document.get("issuer") != self._issuer:
                    # A document for some other issuer means a misconfigured URL
                    # (often just a missing trailing slash). Fail loudly.
                    raise AccountsUnavailable(
                        "Discovery document does not match the configured issuer"
                    )
                self._discovery = document
            value = self._discovery.get(field)
        if not isinstance(value, str) or not value:
            raise AccountsUnavailable(f"Identity provider does not publish {field}")
        return value

    def _signing_key(self, kid: object) -> PyJWK:
        if not isinstance(kid, str) or not kid:
            raise AuthenticationError("Token names no signing key")
        with self._lock:
            key = self._keys.get(kid)
            recently = (
                self._keys_fetched_at is not None
                and self._clock() - self._keys_fetched_at < KEY_REFRESH_INTERVAL
            )
        if key is not None:
            return key
        if recently:
            raise AuthenticationError("Unknown signing key")

        jwks_uri = self._discovered("jwks_uri")
        document = self._fetch(jwks_uri, {})
        try:
            key_set = PyJWKSet.from_dict(document)
        except (jwt.PyJWTError, TypeError, KeyError) as exc:
            raise AccountsUnavailable("Identity provider sent an unreadable key set") from exc
        with self._lock:
            self._keys = {k.key_id: k for k in key_set.keys if k.key_id}
            self._keys_fetched_at = self._clock()
            key = self._keys.get(kid)
        if key is None:
            raise AuthenticationError("Unknown signing key")
        return key
