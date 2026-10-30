"""Auth0: sign-in through standard OpenID Connect, plus closing accounts.

Signing in is the generic `OidcProvider`, unchanged. The only Auth0-specific
part is `delete_account`, which uses Auth0's Management API, because closing
an account is not part of the OpenID Connect standard.

The Management API needs its own credentials: a Machine to Machine
application in Auth0, allowed the `delete:users` permission and nothing else.
Its client id is configuration; its client secret is a secret file.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .model import Credential, Identity, Profile
from .oidc import HTTP_TIMEOUT, OidcProvider
from .service import AccountsUnavailable

#: Renew the Management API token this long before Auth0 says it expires.
TOKEN_MARGIN_SECONDS = 60

#: (status, parsed JSON body or None). Network failures raise AccountsUnavailable.
Response = tuple[int, Any]
Request = Callable[[str, str, Mapping[str, str], Mapping[str, Any] | None], Response]


def http_request(
    method: str, url: str, headers: Mapping[str, str], body: Mapping[str, Any] | None
) -> Response:
    """Send one request. Any status comes back; only a dead network raises."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data else {}),
            **headers,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return response.status, _json(response.read())
    except urllib.error.HTTPError as exc:
        with exc:  # an error response is still an open connection
            return exc.code, _json(exc.read())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AccountsUnavailable("Auth0 unreachable") from exc


def _json(raw: bytes) -> Any:
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


class Auth0Provider:
    """An IdentityProvider for Auth0. Thread-safe."""

    def __init__(
        self,
        issuer: str,
        audience: str,
        client_id: str,
        client_secret: str,
        *,
        algorithms: Sequence[str] = ("RS256",),
        sign_in: OidcProvider | None = None,
        request: Request = http_request,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._sign_in = sign_in or OidcProvider(issuer, audience, algorithms=algorithms)
        self._issuer = issuer
        # The tenant's own address. A custom domain cannot be used here:
        # Auth0 serves the Management API only on the tenant domain.
        base = issuer.rstrip("/")
        self._token_url = f"{base}/oauth/token"
        self._management_api = f"{base}/api/v2/"
        self._client_id = client_id
        self._client_secret = client_secret
        self._request = request
        self._clock = clock
        self._lock = threading.Lock()
        self._token: str | None = None
        self._token_expires_at = 0.0

    # --- Sign-in: plain OpenID Connect ---------------------------------------

    def verify(self, token: str) -> Credential:
        return self._sign_in.verify(token)

    def profile(self, token: str) -> Profile:
        return self._sign_in.profile(token)

    # --- Closing accounts: Auth0's Management API ----------------------------

    def delete_account(self, identity: Identity) -> bool:
        if identity.issuer != self._issuer:
            return False  # signed in through another provider; not ours to close
        # In Auth0 the token's subject is the user id, e.g. "google-oauth2|1029".
        url = self._management_api + "users/" + urllib.parse.quote(identity.subject, safe="")

        status = self._delete(url, renew=False)
        if status == 401:
            # Our cached token was revoked or rotated; get a fresh one, once.
            status = self._delete(url, renew=True)
        if status in (200, 204, 404):
            return True  # 404: already gone, which is what we wanted
        raise AccountsUnavailable(f"Auth0 refused to delete the account ({status})")

    def _delete(self, url: str, *, renew: bool) -> int:
        token = self._management_token(renew=renew)
        status, _ = self._request("DELETE", url, {"Authorization": f"Bearer {token}"}, None)
        return status

    def _management_token(self, *, renew: bool) -> str:
        with self._lock:
            if not renew and self._token and self._clock() < self._token_expires_at:
                return self._token
        status, body = self._request(
            "POST",
            self._token_url,
            {},
            {
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "audience": self._management_api,
            },
        )
        if status != 200 or not isinstance(body, dict) or not body.get("access_token"):
            # Usually a wrong client id or secret, or the application is not
            # allowed to use the Management API.
            raise AccountsUnavailable(f"Auth0 refused the Management API credentials ({status})")
        lifetime = float(body.get("expires_in", 0))
        with self._lock:
            self._token = body["access_token"]
            self._token_expires_at = self._clock() + max(0.0, lifetime - TOKEN_MARGIN_SECONDS)
            return self._token
