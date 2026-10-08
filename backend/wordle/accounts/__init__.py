"""Player accounts: who is playing, when anyone is.

The rest of the app sees one module, `Accounts`, and one question it answers:
"which player sent this request, if any?" Everything behind that question sits
at two seams and is swappable by configuration alone:

- `IdentityProvider`: proves who someone is. `OidcProvider` speaks plain OpenID
  Connect, so Auth0, Authentik, Keycloak or any other standard provider plugs in
  by changing the issuer URL and audience. No provider is named in the code.
- `PlayerRepository`: remembers players. `PostgresPlayerRepository` for real
  deployments, `InMemoryPlayerRepository` for tests and throwaway runs.

Accounts are optional. A request with no credentials is an anonymous player and
plays exactly as before.
"""

from .model import Identity, Player, Profile
from .repository import InMemoryPlayerRepository, PlayerRepository
from .service import (
    Accounts,
    AccountsUnavailable,
    AuthenticationError,
    IdentityProvider,
    SignInDisabled,
)

__all__ = [
    "Accounts",
    "AccountsUnavailable",
    "AuthenticationError",
    "Identity",
    "IdentityProvider",
    "InMemoryPlayerRepository",
    "Player",
    "PlayerRepository",
    "Profile",
    "SignInDisabled",
]
