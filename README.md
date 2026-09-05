# Wordle

Five letters, five guesses, colour-coded feedback. Plays on a phone or with a
physical keyboard. Protected by one shared password.

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
running it on a VPS, and [IMPROVEMENTS.md](IMPROVEMENTS.md) for planned work.

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
cp .env.example .env                  # then edit it
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # WORDLE_SECRET_KEY
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

Open **http://localhost:8080** and enter the password from `.env`.

The frontend needs no build step and no Node. Any static server will do;
`http.server` is just the one that is already installed.

## Tests

```bash
cd backend
.venv/bin/python -m pytest                  # 124 tests
.venv/bin/python -m pytest --cov=wordle     # 98% coverage
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
| `WORDLE_API_BASE` | where the browser sends API calls | `.env` → `frontend/config.js` |
| `WORDLE_ALLOWED_ORIGINS` | where the browser loaded the page from | `.env` → the API's CORS list |

Get one wrong and the page loads but every request fails. In the browser
console that shows up as a CORS error or "Cannot reach the server".

For local development the defaults already match: frontend on 8080, API on 8000.

## Configuration

Every backend setting reads from a `WORDLE_`-prefixed environment variable, or
from `.env` at the repo root. See [.env.example](.env.example).

| Variable | Default | Notes |
|---|---|---|
| `WORDLE_PASSWORD` | — | Required. Shared password. |
| `WORDLE_SECRET_KEY` | — | Required, 16+ chars. Signs the token. |
| `WORDLE_ALLOWED_ORIGINS` | `http://localhost:8080` | Comma-separated. |
| `WORDLE_API_BASE` | `http://localhost:8000` | Frontend only. |
| `WORDLE_TOKEN_MAX_AGE` | `43200` | Token lifetime, seconds. |
| `WORDLE_MAX_ATTEMPTS` | `5` | Guesses per game. |
| `WORDLE_WORD_LENGTH` | `5` | Must match the word list. |
| `WORDLE_ANSWERS_PATH` | shipped CSV | Override the answer list. |
| `WORDLE_DICTIONARY_PATH` | shipped CSV | Override the allowed-guess list. |
| `WORDLE_GAME_TTL_SECONDS` | `14400` | Abandoned games are dropped after this. |
| `WORDLE_MAX_GAMES` | `10000` | Cap on games held in memory. |
| `WORDLE_LOGIN_MAX_FAILURES` | `10` | Failures before a lockout. |
| `WORDLE_LOGIN_LOCKOUT_SECONDS` | `300` | How long the lockout lasts. |

The API refuses to start without a password and a secret key. There is no
fallback for either, because a default secret is not a secret.

## API

JSON everywhere. Every route except `/healthz` and `/api/login` needs
`Authorization: Bearer <token>`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Liveness. Public. |
| `POST` | `/api/login` | Password in, token out. Public. |
| `GET` | `/api/session` | Is my stored token still good? |
| `POST` | `/api/games` | Start a game. |
| `GET` | `/api/games/{id}` | Current board, for resuming a reload. |
| `POST` | `/api/games/{id}/guesses` | Score a guess. |

```bash
TOKEN=$(curl -s localhost:8000/api/login \
  -H 'Content-Type: application/json' -d '{"password":"letmein"}' | jq -r .token)

curl -s -X POST localhost:8000/api/games -H "Authorization: Bearer $TOKEN"
```

A board looks like this. `answer` stays `null` until the game ends:

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
  "answer": null
}
```

Guess errors are specific, so the page can say something useful: `400` with
`"Enter a valid word"`, `"Guess must be 5 letters"` or `"Guess must contain
letters only"`. A rejected guess costs no attempt. `409` means the game is over,
`404` that it expired or never existed, `401` that the token is missing, forged
or stale.

## How access works

There are no accounts. `POST /api/login` checks the shared password with
`hmac.compare_digest` and returns a token signed with `WORDLE_SECRET_KEY` and
stamped with the time. Every later request carries it in an `Authorization`
header; the API verifies the signature and the age.

A token, not a cookie, because the two halves are separate origins. Cookies
across origins need `SameSite=None; Secure`, which needs HTTPS — awkward when
the deployment target is a bare IP address over plain HTTP.

The token is stored in `localStorage`, so it survives a reload. It is readable
by anything running on the page, which is the same thing that is true of the
password box itself. There is no user data behind it.

Because the frontend is served separately, its HTML and JS are public. They
contain no answers and no password, and every route that matters is gated. What
the password protects is playing, not downloading an empty board.

## Word lists

Two files in `backend/wordle/data/`, because they do different jobs.

| File | Size | Job |
|---|---|---|
| `answers.csv` | 830 | Where the answer comes from. Common words only. |
| `dictionary.csv` | 14,855 | What a guess is allowed to be. |

One word per row under a `word` header. Every row must be a five-letter
alphabetic word; a bad row stops startup with the offending line number rather
than being quietly skipped.

**Why two.** Using one list for both jobs breaks whichever way you size it. A
small list rejects `cards`, `boxes` and `trees` as "not a word", which is
maddening. A large list hands out answers like `aalii` and `zymic`. So answers
are drawn from a curated set, and guesses are checked against a full one.

The answers must all be valid guesses, or a game would be unwinnable.
`WordRepository.default_pair()` checks that at startup rather than leaving a
player to discover it.

Swapping in a database means reimplementing `WordRepository` and nothing else.

## Known limits

- **Games live in memory**, so run exactly one worker. A second worker would not
  see games created by the first. Moving to Redis means implementing the
  `GameStore` protocol.
- **The login throttle is per process** — a speed bump, not a real rate limit.
  Put one at the reverse proxy for an internet-facing deployment.
- **One shared password**, no accounts. Everyone who has it sees the same game.
