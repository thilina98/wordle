# Wordle

Five letters, five guesses, colour-coded feedback. Plays on a phone or with a
physical keyboard. Anyone can play without an account; signing in (email and
password, Google or GitHub) is optional and ties games to a player.

One repository, two applications. They are built, run and deployed separately
and share nothing but the HTTP contract between them.

```
frontend/                     backend/
static files + nginx  ──API──▶  FastAPI
port 8080                       port 8000
```

| | `frontend/` | `backend/` |
|---|---|---|
| What it is | HTML, CSS, vanilla JS | FastAPI service |
| Serves | the page | JSON only |
| Runs on | its own web server | uvicorn |
| Knows about the other | one URL, in `config.js` | one CORS origin |

Neither directory imports from the other. The backend serves no HTML; the
frontend contains no game rules.

See [PLAN.md](PLAN.md) for the design, [DEPLOYMENT.md](DEPLOYMENT.md) for
running it on a VPS, and [IMPROVEMENTS.md](IMPROVEMENTS.md) for ideas not yet built.

## Why the split is strict

The server decides which words are valid and what colour each letter gets. The
answer is not sent to the browser until the game is over. So the rules have one
tested implementation rather than two that drift apart, and the frontend cannot
be edited into cheating.

## Run it locally

Two terminals. Both are needed — the page will load without the backend, but
nothing in it will work.

**Once, to set up:**

```bash
python3 -m venv .venv                 # a venv holding just Poetry
./.venv/bin/pip install poetry

cd backend
../.venv/bin/poetry install --extras dev

cd ..
cp backend/.env.example backend/.env   # backend settings; defaults suit local
cp frontend/.env.example frontend/.env # frontend settings (Docker only)

mkdir -p secrets                      # only needed for sign-in; see backend/ACCOUNTS.md
python3 -c "import secrets; print(secrets.token_urlsafe(32), end='')" > secrets/wordle_database_password
printf "%s" "PASTE_DELETION_APP_CLIENT_SECRET" > secrets/wordle_auth0_deletion_app_client_secret   # see backend/ACCOUNTS.md
chmod 600 secrets/wordle_*
```

**Terminal 1 — the API:**

```bash
cd backend
.venv/bin/python -m uvicorn wordle.app:create_app --factory --reload --port 8000
```

**Terminal 2 — the frontend:**

```bash
cd frontend
python3 -m http.server 8080
```

Open **http://localhost:8080**. With no `WORDLE_AUTH_ISSUER` set, sign-in is
off and every game is anonymous; no database is needed.

The frontend needs no build step and no Node. Any static server will do;
`http.server` is just the one that is already installed.

## Run it in Docker

```bash
docker compose up -d --build
```

Page on **http://localhost:8080**, API on **8000**. Both ports are needed: the
browser fetches the page from 8080 and then calls 8000 directly.

| File | For |
|---|---|
| `docker-compose.yml` | Everywhere. Published ports, hardened, works on Mac and Linux. |
| `docker-compose.prod.yml` | The VPS, when host networking is needed. See DEPLOYMENT.md. |
| `docker-compose.dev.yml` | `docker compose ... watch` — syncs edits into the containers. |

## Tests

```bash
cd backend
.venv/bin/python -m pytest                  # 154 tests
.venv/bin/python -m pytest --cov=wordle     # 97% coverage
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

The tests assert HTTP and function contracts — status codes, colour lists,
response shapes — so refactoring the internals does not rewrite the suite.

There is no JavaScript test suite. Node is not part of this project's
toolchain, and a suite that cannot run is worse than none. The frontend is kept
free of game rules so there is nothing there to test.

## The two URLs that must match

This is the only fiddly part of running the two halves separately. Both values
describe what the **browser** sees, not what the containers see.

| Setting | Meaning | Set in |
|---|---|---|
| `WORDLE_API_BASE` | where the browser sends API calls | `frontend/.env` → `frontend/config.js` |
| `WORDLE_ALLOWED_ORIGINS` | where the browser loaded the page from | `backend/.env` → the API's CORS list |

Get one wrong and the page loads but every request fails. In the browser
console that shows up as a CORS error or "Cannot reach the server".

For local development the defaults already match: frontend on 8080, API on 8000.

## Configuration

Each application has its own settings file; there is no shared one at the repo
root. Every backend setting reads from a `WORDLE_`-prefixed environment
variable, or from `backend/.env`. See
[backend/.env.example](backend/.env.example) and
[frontend/.env.example](frontend/.env.example).

| Variable | Default | Notes |
|---|---|---|
| `WORDLE_AUTH_ISSUER` | unset | Identity provider's issuer URL. Unset turns sign-in off. |
| `WORDLE_AUTH_AUDIENCE` | unset | This API's identifier at the provider. Required with an issuer. |
| `WORDLE_AUTH_ALGORITHMS` | `RS256` | Accepted token signatures. Asymmetric only. |
| `WORDLE_AUTH_LINK_VERIFIED_EMAILS` | `true` | Join sign-in methods that share a verified email. |
| `WORDLE_AUTH_PROVIDER` | `oidc` | `auth0` also closes the Auth0 account when a player deletes theirs. `oidc` works with any provider but leaves it open. |
| `WORDLE_AUTH0_DELETION_APP_CLIENT_ID` | unset | `auth0` only. The Machine to Machine app allowed to delete users. |
| `WORDLE_AUTH0_DELETION_APP_CLIENT_SECRET` | unset | `auth0` only. **From `secrets/`.** |
| `WORDLE_DATABASE_URL` | unset | PostgreSQL URL, no password. Required when sign-in is on. |
| `WORDLE_DATABASE_PASSWORD` | unset | **From `secrets/`.** |
| `WORDLE_SECRETS_DIR` | auto | Override where secret files are found. |
| `WORDLE_ALLOWED_ORIGINS` | `http://localhost:8080` | Comma-separated. |
| `WORDLE_API_BASE` | `http://localhost:8000` | Frontend, in `frontend/.env`. |
| `WORDLE_AUTH_ISSUER`, `WORDLE_AUTH_AUDIENCE`, `WORDLE_AUTH_LOGIN_APP_CLIENT_ID` | unset | Frontend, in `frontend/.env`: sign-in button. All three or none. See [backend/ACCOUNTS.md](backend/ACCOUNTS.md). |
| `WORDLE_DEFAULT_WORD_LENGTH` | `5` | Length used when a game does not ask for one. Must be installed. |
| `WORDLE_WORD_LISTS_DIR` | shipped lists | Directory of word lists, one subdirectory per length. |
| `WORDLE_ACTIVE_GAMES_STORE` | `sqlite` | `sqlite` keeps games across a restart; `memory` loses them. |
| `WORDLE_ACTIVE_GAMES_DB_PATH` | `data/games.db` | The SQLite file for games being played. Mount a volume on its folder. |
| `WORDLE_ACTIVE_GAMES_TTL_SECONDS` | `14400` | A game untouched this long is dropped. |
| `WORDLE_ACTIVE_GAMES_MAX` | `10000` | Most games kept at once; the least recently played go first. |
| `WORDLE_SCORING_*` | unset | Scoring constants, only when sign-in is off (no database). All seven required then; ignored with a database. See [Scoring](#scoring). |

The API needs no secrets to start. Half a sign-in configuration (an issuer
without an audience, or no database URL) stops it at startup rather than at
the first sign-in. So does sign-in off with a `WORDLE_SCORING_*` value missing,
or sign-in on with no active scoring version in the database.

**Secrets live in `secrets/`, never in a `.env` file** — one file per secret,
the same directory in every environment (`/run/secrets` in Docker, `secrets/`
from source). Compose hands each `.env` file to its container as environment
variables, so a secret placed there would show up in `docker inspect`.

`backend/.env` and `frontend/.env` hold the per-machine, non-secret settings:
which URLs the browser uses, sign-in, and the timeouts. Both are gitignored, so
your laptop's copies and the VPS copies differ. See
[secrets/README.md](secrets/README.md).

## API

JSON everywhere. No route needs a token. Send `Authorization: Bearer <token>`
(an access token from the identity provider) to play as a signed-in player.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Liveness. |
| `GET` | `/api/players/me` | The signed-in player. The first call registers them. Token required. |
| `DELETE` | `/api/players/me` | Delete the signed-in player, their games and (with `auth0`) their Auth0 account. Token required. |
| `POST` | `/api/games` | Start a game. |
| `GET` | `/api/games/{id}` | Current board, for resuming a reload. |
| `POST` | `/api/games/{id}/start` | Start the clock, on the first keystroke. |
| `POST` | `/api/games/{id}/guesses` | Score a guess. |

```bash
curl -s -X POST localhost:8000/api/games                                   # anonymous
curl -s -X POST localhost:8000/api/games -H "Authorization: Bearer $TOKEN" # as a player
```

A board looks like this. `answer` and `score` stay `null` until the game ends:

```json
{
  "game_id": "9omWeUcuVJoddWKD9GGC1Q",
  "word_length": 5,
  "max_attempts": 5,
  "attempts": [{"guess": "state", "colours": ["miss","miss","hit","miss","hit"]}],
  "attempts_remaining": 4,
  "is_over": false,
  "is_won": false,
  "letter_states": {"s": "miss", "t": "miss", "a": "hit", "e": "hit"},
  "answer": null,
  "score": null
}
```

Guess errors are specific, so the page can say something useful: `400` with
`"Enter a valid word"`, `"Guess must be 5 letters"` or `"Guess must contain
letters only"`. A rejected guess costs no attempt. `409` means the game is over,
`404` that it expired, never existed or belongs to another player, `401` that
a token was sent and is forged, expired or malformed (a bad token is never
treated as anonymous), `503` that the identity provider or database is down.

## How access works

Anyone can play without an account. Signing in is optional and happens at an
identity provider (Auth0 today), never in this API: the frontend sends the
player there, gets back an access token, and sends it with each request. The
API checks the token's signature against the provider's published keys and
turns it into a player of our own, kept in PostgreSQL.

A game started while signed in belongs to that player; anyone else gets a 404.
A game started anonymously is open to whoever holds its unguessable id, as
every game was before accounts.

No provider and no database is named outside `backend/wordle/accounts/`.
Switching to another OpenID Connect provider (Authentik, Keycloak...) is a
configuration change; replacing PostgreSQL needs a new storage class. See
[backend/ACCOUNTS.md](backend/ACCOUNTS.md) for the design, provider setup and
the database schema.

### Sign-in on or off

Two settings in `backend/.env` decide whether players can sign in:

| `WORDLE_AUTH_ISSUER` and `WORDLE_AUTH_AUDIENCE` | Result |
|---|---|
| Both set | **Sign-in on.** Players can sign in through the provider, and their games belong to their account. Anonymous play still works. Needs PostgreSQL. |
| Neither set | **Sign-in off.** Anonymous play only, exactly as before accounts existed. The API never contacts the provider or PostgreSQL, and answers any token with "Sign-in is not enabled on this server". Useful before the provider is set up. |
| Only one set, or set to an empty value | The API refuses to start. |

To check which mode a running server is in, send it a fake token shaped like a
real one:

```bash
curl -i -H "Authorization: Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6InByb2JlIn0.e30.x" \
  localhost:8000/api/players/me
```

| Reply | Meaning |
|---|---|
| `401` "Unknown signing key" | Sign-in is on and working: the API reached the provider, fetched its keys and rejected the fake token. |
| `503` "Sign-in is unavailable" | Sign-in is on but the provider cannot be reached, or `WORDLE_AUTH_ISSUER` does not match it exactly (check the trailing `/`). |
| `401` "Sign-in is not enabled on this server" | Sign-in is off. |

A request with no token at all gets "Sign in to do this" in both modes, so it
cannot tell them apart.

## Word lists

One directory per word length, named for the length, each holding two files
because they do different jobs.

```
backend/wordle/data/
└── 5/
    ├── answers.csv      830 words
    └── dictionary.csv   14,855 words
```

| File | Job |
|---|---|
| `answers.csv` | Where the answer comes from. Common words only. |
| `dictionary.csv` | What a guess is allowed to be. |

One word per row under a `word` header. Every row must be alphabetic and as
long as the directory it sits in; a bad row stops startup with the offending
line number rather than being quietly skipped. The directory name is the
assertion, so a list filed under the wrong length fails on load.

**Adding a length.** Create the directory, drop in the two files, and point
`WORDLE_WORD_LISTS_DIR` at the root holding it. No code changes. Clients then
ask for it per game:

```
POST /api/games   {"word_length": 6}
```

Only the shipped five-letter lists are installed, so that is the only length
available out of the box. A request for a length with no lists is a 400 naming
the lengths that do exist, and an omitted `word_length` uses
`WORDLE_DEFAULT_WORD_LENGTH`.

## Scoring

A finished game is worth a score. Normal mode — one attempt per letter — is
out of 10. Playing with fewer attempts is harder, and scores more. The score
arrives on the board itself, in the `score` field, so there is no second
request to make. The page shows it on the end-of-game card after a win; a loss
scores nothing, so nothing is shown.

```json
{
  "word_length": 5, "max_attempts": 4, "is_won": true, "winning_attempt": 3,
  "game_time_seconds": 120.0, "base": 58.48, "time_bonus": 7.02,
  "multiplier": 1.25, "raw_score": 81.87, "score": 6.82
}
```

Only `score` is meant for a player. The rest is the working, kept so a score
can be explained without the page reimplementing the arithmetic.

Three things decide it:

**How few guesses it took.** A win on attempt 2 is worth the full 100 base
points; a win on attempt `word_length` keeps a fifth of that, and the attempts
in between decay smoothly from one to the other. Attempt 1 scores nothing — the
player had no feedback to act on, so it was luck, not play. It still counts as
a win everywhere else.

**How fast.** Up to 20% of the base on top, falling linearly to zero over a
window of 60 seconds per letter. The cap is deliberately small: solving it in
fewer guesses always beats solving it faster. Past the window the bonus is
zero, never negative.

**How much help the game gave.** Normal mode is one attempt per letter. Each
attempt fewer multiplies the whole score by 1.25, each attempt more divides by
it. This is the only thing `max_attempts` affects — the base and the time
window are measured against the word, not against the allowance.

So 10.00 is the best normal-mode game, at every word length. One attempt fewer
tops out at 12.50, one attempt more at 8.00. The score is not capped at 10.

The clock runs from the player's first keystroke, not from `POST /api/games`: a
board can sit untouched while its player reads the rules, and that is not time
spent playing. The client marks the moment with `POST /api/games/{id}/start`,
which is idempotent, so it can fire on every keystroke and only the first one
counts. The server keeps the time, not the page, so a doctored client cannot
claim a four-second game. A game that never calls it is timed from its first
guess; a game that never reaches the server at all is scored as if it used its
whole window, because withholding the clock must not pay.

The formula lives in `backend/wordle/scoring.py`; its constants do not.

| Sign-in | Constants come from |
|---|---|
| On (PostgreSQL) | The active row in `scoring_versions`. Cached in memory, refreshed every 4 hours and whenever a recorded game sees a newer version. |
| Off (no database) | The seven `WORDLE_SCORING_*` settings. Placeholders with version 1's values are in `backend/.env.example`. |

Every recorded game keeps the scoring version it was played under, so a rule
change never loses the original score.

## Statistics

A signed-in player's finished games are kept in PostgreSQL, one row each, and
added up per player, word length and difficulty. Anonymous games are never
recorded, and cannot be claimed after signing in.

```
GET /api/players/me/stats                                   every game
GET /api/players/me/stats?word_length=5                     one mode, every difficulty
GET /api/players/me/stats?difficulty=hard                   one difficulty, every mode
GET /api/players/me/stats?word_length=5&difficulty=hard     one combination
```

**Mode** is the word length. **Difficulty** is the attempt allowance against
it: `easy` (more attempts than letters), `normal` (one per letter), `hard`
(fewer). Each game keeps the label it was played under.

| Figure | Means |
|---|---|
| `games`, `wins`, `losses`, `win_percentage` | `losses` includes abandoned games. |
| `first_attempt_wins`, `last_attempt_wins` | Won on attempt 1; won on the last attempt allowed. |
| `total_score`, `highest_score` | Under the active scoring version. |
| `average_score` | Over **scored games only**: wins on attempt 2 or later. Losses and attempt-1 wins score 0 and are left out. |
| `fastest_win_ms`, `average_win_ms` | Wins on attempt 2 or later only. |
| `current_streak`, `best_streak` | Wins in a row. Only when both `word_length` and `difficulty` are given; null otherwise. A loss elsewhere does not break it. |
| `guess_distribution` | Wins by the attempt they were won on. |

Figures that would divide by zero are null.

**What counts.** A win or a loss counts. A game left after two or more guesses
counts as a loss (`abandoned`); after one guess it is ignored. A game is left
when the player starts another in the same mode and difficulty, or when it
expires.

**Nothing is lost to an outage.** A finished game waits in the SQLite store
until PostgreSQL has it. The server retries every minute, in the order the
games ended, and the player gets their board either way.

### Data scripts

Migrations change the schema and run on their own at startup. Changes to
data are data scripts in `backend/wordle/db/data_scripts/`, run by hand, once
each:

```bash
python -m wordle.db data-scripts                                     # list, with what has run
python -m wordle.db run-data-script 0001_seed_scoring_version_1     # run one
```

`0001_seed_scoring_version_1` must run once before the server first starts
with sign-in on; until then it refuses to start. In Docker, see
[DEPLOYMENT.md](DEPLOYMENT.md).

## Game shape

A new game takes its shape from the request, falling back to the server's
defaults for anything left out.

```
POST /api/games   {"word_length": 6, "max_attempts": 7}
POST /api/games   {}
```

| Field | Default | Bound by |
|---|---|---|
| `word_length` | `WORDLE_DEFAULT_WORD_LENGTH` | The word lists installed. |
| `max_attempts` | One guess per letter | 2 to the length plus two. |

**Attempts follow the word.** A five-letter game gets five guesses and allows
between two and seven; a seven-letter game gets seven and allows between two
and nine. A longer word is a harder word, so a flat number would be generous at
four letters and stingy at seven. Two is the floor everywhere, because a single
guess gives the player no feedback to act on.

```
POST {"word_length": 4}                       -> 4 letters, 4 attempts
POST {"word_length": 7}                       -> 7 letters, 7 attempts
POST {"word_length": 4, "max_attempts": 7}    -> 400, a 4-letter game allows at most 6
```

The rule lives in `GameState`, which already knows both the word and the count,
and is enforced wherever a game is built rather than only at the HTTP edge. The
request schema deliberately does not carry the upper bound, because the bound
depends on the length and only the game knows that.

There is no setting for the attempt count. The derived default adapts to the
word where a fixed number could not, and a client that wants something else
asks for it per game.

**Why two.** Using one list for both jobs breaks whichever way you size it. A
small list rejects `cards`, `boxes` and `trees` as "not a word", which is
maddening. A large list hands out answers like `aalii` and `zymic`. So answers
are drawn from a curated set, and guesses are checked against a full one.

The answers must all be valid guesses, or a game would be unwinnable.
`WordRepository.default_pair()` checks that at startup rather than leaving a
player to discover it.

Swapping in a database means reimplementing `WordRepository` and nothing else.

## Storage

Games being played go in their own SQLite file, `WORDLE_ACTIVE_GAMES_DB_PATH`,
apart from the main PostgreSQL database, so destroying and rebuilding the
container does not end anyone's game. In Docker that directory is a named volume, `wordle-data`, which
outlives `docker compose down` and only goes away with `docker volume rm`.

`WORDLE_ACTIVE_GAMES_STORE=memory` switches to the in-process store, which is faster and
loses everything on restart. Both implement the same `GameStore` protocol and
run against the same contract tests.

## Known limits

- **Run exactly one worker.** SQLite takes one writer. Scaling out means
  Postgres behind the `GameStore` protocol, as players already are.
- **No rate limit.** Game routes are open to anonymous players, so put a rate
  limit at the reverse proxy for an internet-facing deployment.
