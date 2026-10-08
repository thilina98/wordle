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
| `IdentityProvider`: proves who sent a token | `OidcProvider` (standard OpenID Connect) | `tests/fakes.py` |
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

## Database schema

`wordle/accounts/migrations/0001_players.sql`. Migrations run automatically
at startup, under an advisory lock so two servers starting together do not
race. Applied versions are recorded in `schema_migrations`.

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
4. **Create the frontend application** (needed when the frontend is built):
   a Single Page Application, with the three connections enabled. It must ask
   for `audience=https://wordle-api` and `scope=openid profile email`, so the
   access token is meant for this API and can also read the player's profile.
5. **Configure the API**, in `backend/.env`:

   ```
   WORDLE_AUTH_ISSUER=https://<your-tenant>.auth0.com/
   WORDLE_AUTH_AUDIENCE=https://wordle-api
   ```

   The issuer must match the `issuer` in
   `https://<your-tenant>.auth0.com/.well-known/openid-configuration`
   exactly, including Auth0's trailing slash. If it does not match, the API
   answers 503 and does not accept any token.

## Running the PostgreSQL tests

```bash
docker run -d --name wordle-test-db -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:17-alpine
WORDLE_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/postgres \
  .venv/bin/pytest tests/test_accounts.py
```

The tests drop and recreate the accounts tables. Never point them at a real
database.
