# Player accounts

Signing in is optional. A request with no `Authorization` header is an
anonymous player and plays exactly as before. A request with a valid token
plays as a player, whose games nobody else can open. Statistics are not stored
yet; this is the identity layer they will hang off.

Sign-in methods: email and password, Google, and GitHub. All three are set up
at the identity provider. This API never sees a password and has no code for
any of them.

## Design

Everything lives in `wordle/accounts/`. The rest of the app knows one module
and one method:

```python
accounts.identify(authorization_header) -> Player | None
```

`None` means anonymous. Bad credentials raise `AuthenticationError` (401), and
are never downgraded to anonymous. A provider or database outage raises
`AccountsUnavailable` (503). Sign-up is not a separate step: the first time an
identity is seen, it is registered.

Behind that interface are two seams, each with two adapters:

| Seam | Production adapter | Test adapter |
|---|---|---|
| `IdentityProvider`: proves who sent a token, closes accounts | `OidcProvider` (any OpenID Connect provider), `Auth0Provider` | `tests/fakes.py` |
| `PlayerRepository`: remembers players | `PostgresPlayerRepository` | `InMemoryPlayerRepository` |

The repository contract tests (`tests/test_accounts.py`) run against both
adapters, so they cannot drift apart. PostgreSQL joins in when
`WORDLE_TEST_DATABASE_URL` points at an empty, throwaway database.

### Swapping the identity provider: configuration only

`OidcProvider` reads the provider's keys and userinfo endpoint from
`<issuer>/.well-known/openid-configuration`. Moving from Auth0 to Authentik,
Keycloak or anything else that speaks OpenID Connect means changing two values:

```
WORDLE_AUTH_ISSUER=https://auth.example.com/application/o/wordle/
WORDLE_AUTH_AUDIENCE=<the new provider's audience for this API>
```

Players survive the move. Every player has our own id (`player_id`); the
provider's id lives only in `player_identities`. When someone signs in through
the new provider, their identity is joined to their existing player by
verified email, so their games and (later) stats follow them. A player whose
email was never verified will arrive as a new player.

### Swapping the database: one new adapter

`PostgresPlayerRepository` is the only code that knows PostgreSQL exists.
Another database means a new class with `find` and `register` beside it, plus
one line in `app.py` to choose it. Nothing in the game or the API changes, and
the existing contract tests check the new adapter.

### Joining sign-in methods

A new identity joins an existing player only when the provider says its email
is verified **and** the existing player's matching email was verified too.
Otherwise, anyone could take over an account by typing someone's email into a
sign-up form. Turn it off with `WORDLE_AUTH_LINK_VERIFIED_EMAILS=false`.

Two sign-ins with the same email, made in the same instant by two methods
that have never been seen before, can still produce two players. That is rare,
and accepted for now.

### Game ownership

`GameStore.create(game, owner)` and `GameStore.get(game_id, viewer)`. An owned
game is visible to its owner only, and someone else's game looks exactly like
a game that does not exist (404). An unowned (anonymous) game is visible to
anyone with its id. A signed-in player can still finish a game they started
anonymously.

### Deleting a player

`DELETE /api/players/me`, in this order:

1. **Closes the player's accounts at the provider**, one per sign-in method
   (email, Google and GitHub are separate Auth0 accounts). If the provider
   fails, nothing is deleted and the answer is 503, so the player can retry.
   An account already gone counts as closed, so a retry never gets stuck.
2. **Removes the player** and their sign-in identities from PostgreSQL.
3. **Removes their games** from the active games file.

It answers 204. Afterwards, any token issued before the deletion is refused
(401, "This account was deleted"), so a second open tab cannot bring the
player back. Signing up again later works and makes a new player.

Closing provider accounts is not part of OpenID Connect, so it depends on
`WORDLE_AUTH_PROVIDER`:

| Setting | Signs in with | Deleting a player |
|---|---|---|
| `oidc` | any OpenID Connect provider | removes our data; the provider account stays open (logged) |
| `auth0` | Auth0 | removes our data and closes the Auth0 accounts |

Switching to another provider stays a settings change with `oidc`. Writing a
provider class for it (like `wordle/accounts/auth0.py`: the shared OpenID
Connect sign-in plus that provider's delete call) adds account closing.

To refuse old tokens, the `deleted_identities` table keeps, for each deleted
sign-in, a SHA-256 fingerprint of it and the time of deletion. Not the
provider's id, not the email: nothing there identifies a person.

## Database schema

`wordle/db/migrations/0001_players.sql` and `0002_deleted_identities.sql`.
Every module's migrations share that one folder (statistics is `0003`), and
`wordle.db.Database` owns the connection pool they all borrow. Migrations run
automatically at startup, under an advisory lock so two servers starting
together do not race. Applied versions are recorded in `schema_migrations`.
Migrations change the schema only; data changes are data scripts, in
`wordle/db/data_scripts/`, run by hand (see the main README).

```
players                              player_identities
-------------------------------      ---------------------------------------
player_id     UUID  PK               identity_id    BIGINT identity  PK
display_name  TEXT  1..64 chars      player_id      UUID  FK -> players, ON DELETE CASCADE
created_at    TIMESTAMPTZ            issuer         TEXT  \  UNIQUE together
                                     subject        TEXT  /
                                     email          TEXT  (nullable, <= 320)
                                     email_verified BOOLEAN
                                     created_at     TIMESTAMPTZ
```

- `player_id` is a UUID because it leaves the server and must not reveal how
  many players there are. `identity_id` never leaves, so it is a plain
  identity column.
- `player_identities` is indexed on `player_id` (PostgreSQL does not index
  foreign keys itself), and has a partial index on `lower(email) WHERE
  email_verified`, the exact expression the linking query uses.
- Email is stored only so that a new sign-in method can be joined to an
  existing player. It is never returned by the API.

## Setting up Auth0

1. **Create an API.** Applications → APIs → Create API. Name it `Wordle`, and
   give it an identifier such as `https://wordle-api`. The identifier is never
   called; it is the audience. Leave the signing algorithm as RS256.
2. **Turn on email and password.** Authentication → Database →
   `Username-Password-Authentication`. Keep email verification on: an
   unverified email never joins an existing player.
3. **Turn on Google and GitHub.** Authentication → Social. Auth0's development
   keys work for trying it out; production needs your own OAuth app from
   Google and GitHub. For GitHub, request the `user:email` permission, or
   players with a private email arrive without one and cannot be joined by
   email.
4. **The login app** (the frontend signs players in through it).
   Applications → Applications → your login app, which must be a **Single
   Page Application** (shown as Application Type on its Settings tab). On
   its Settings tab, enter the address the game page is opened from, in
   three fields (for local development, `http://localhost:8080`):
   - **Allowed Callback URLs:** `http://localhost:8080/` (where Auth0 sends
     the player back after signing in; mind the final slash)
   - **Allowed Logout URLs:** `http://localhost:8080/`
   - **Allowed Web Origins:** `http://localhost:8080` (no slash)

   Add the production address to each, comma-separated, when you deploy.
   On its **Connections** tab, turn on email and password, Google and GitHub.
   Then put its **Client ID** in `frontend/.env` (see below). The frontend asks
   for `audience=https://wordle-api` and `scope=openid profile email` by
   itself. If signing in fails with "not authorized to access resource
   server", allow the login app on your API: Applications → APIs → Wordle →
   the tab listing applications.
5. **Configure the API**, in `backend/.env`:

   ```
   WORDLE_AUTH_ISSUER=https://<your-tenant>.auth0.com/
   WORDLE_AUTH_AUDIENCE=https://wordle-api
   ```

   The issuer must match the `issuer` in
   `https://<your-tenant>.auth0.com/.well-known/openid-configuration`
   exactly, including Auth0's trailing slash. If it does not match, the API
   answers 503 and does not accept any token.
6. **Let the API close accounts.** Applications → Applications → Create
   Application. Name it `Wordle API account deletion`, choose **Machine to
   Machine Applications**, and click Create. When asked which API it may call,
   choose **Auth0 Management API**, and under permissions tick only
   **`delete:users`**. Then, on its Settings tab:
   - copy **Client ID** into `backend/.env`:

     ```
     WORDLE_AUTH_PROVIDER=auth0
     WORDLE_AUTH0_DELETION_APP_CLIENT_ID=<the Client ID>
     ```

   - copy **Client Secret** into the file `secrets/wordle_auth0_deletion_app_client_secret`,
     on its own, with nothing else in the file.

   Grant only `delete:users`: this application's secret can then close
   accounts and do nothing else. If you later give Auth0 a custom domain,
   keep the issuer on the tenant domain for this, because Auth0 serves its
   Management API only there.

## Configuring the frontend

`frontend/.env` (Docker), or `frontend/config.js` when running the page
from source. All three or none; with none, the page has no sign-in button:

```
WORDLE_AUTH_ISSUER=<same as backend/.env>
WORDLE_AUTH_AUDIENCE=<same as backend/.env>
WORDLE_AUTH_LOGIN_APP_CLIENT_ID=<the login app's Client ID>
```

The page signs in through `frontend/auth.js`, which speaks plain OpenID
Connect through the vendored oidc-client-ts library (`frontend/vendor/`). No
Auth0 code runs in the browser, so another provider is again a settings
change. The sign-in is kept in the browser's local storage until the token
expires (24 hours by Auth0's default); then the player is asked to sign in
again.

## Running the PostgreSQL tests

```bash
docker run -d --name wordle-test-db -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:17-alpine
WORDLE_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/postgres .venv/bin/pytest tests/test_accounts.py tests/test_stats.py
```

The tests drop and recreate every table. Never point them at a real
database.
