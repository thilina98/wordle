# Wordle

Five letters, five guesses, colour-coded feedback. Plays on a phone or with a
physical keyboard. The whole site sits behind one shared password.

- **Backend** — FastAPI. Owns every game rule and serves the frontend.
- **Frontend** — vanilla JS. Draws what the API returns and nothing more.
- **Words** — a CSV, loaded and validated at startup.

See [PLAN.md](PLAN.md) for the design and [DEPLOYMENT.md](DEPLOYMENT.md) for
running it on a VPS.

## Why the frontend holds no rules

The server decides which words are valid and what colour each letter gets. The
answer is not sent to the browser until the game is over. That keeps the game
honest and means the rules have one tested implementation rather than two that
can drift apart.

## Run it locally

Requires Python 3.11 or newer. Poetry lives in a venv of its own, so it never
mixes with the project's dependencies.

```bash
# One-time: a venv holding just Poetry
python3 -m venv .venv
./.venv/bin/pip install poetry

# Project dependencies, into backend/.venv
cd backend
../.venv/bin/poetry install --extras dev
```

Set the two required secrets:

```bash
cp ../.env.example .env
# then edit backend/.env
python -c "import secrets; print(secrets.token_urlsafe(32))"   # for WORDLE_SECRET_KEY
```

Start it:

```bash
cd backend
.venv/bin/python -m uvicorn wordle.app:create_app --factory --reload --port 8000
```

Open http://127.0.0.1:8000 and enter the password from `.env`.

## Tests

```bash
cd backend
.venv/bin/python -m pytest                          # 102 tests
.venv/bin/python -m pytest --cov=wordle             # with coverage
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

The tests assert HTTP and function contracts — status codes, colour lists,
response shapes — so refactoring the internals does not rewrite the suite.

There is no JavaScript test suite. Node is not part of this project's
toolchain, and a suite that cannot run is worse than none. The frontend is kept
free of game rules so there is nothing there to test.

## Configuration

Every setting reads from a `WORDLE_`-prefixed environment variable, or from
`backend/.env`. See [.env.example](.env.example).

| Variable | Default | Notes |
|---|---|---|
| `WORDLE_PASSWORD` | — | Required. Site password. |
| `WORDLE_SECRET_KEY` | — | Required, 16+ chars. Signs the session cookie. |
| `WORDLE_COOKIE_SECURE` | `false` | Set `true` only when serving HTTPS. |
| `WORDLE_SESSION_MAX_AGE` | `43200` | Session lifetime, seconds. |
| `WORDLE_MAX_ATTEMPTS` | `5` | Guesses per game. |
| `WORDLE_WORD_LENGTH` | `5` | Must match the word list. |
| `WORDLE_WORD_LIST_PATH` | shipped CSV | Override the word list. |
| `WORDLE_GAME_TTL_SECONDS` | `14400` | Abandoned games are dropped after this. |
| `WORDLE_MAX_GAMES` | `10000` | Cap on games held in memory. |
| `WORDLE_LOGIN_MAX_FAILURES` | `10` | Failures before a lockout. |
| `WORDLE_LOGIN_LOCKOUT_SECONDS` | `300` | How long the lockout lasts. |
| `WORDLE_FRONTEND_DIR` | `../frontend` | Where the HTML, CSS and JS live. |

The app refuses to start without a password and a secret key. There is no
fallback default for either, because a default secret is not a secret.

## API

Every route needs the session cookie set by `POST /login`. Anonymous requests
get 401, or a redirect to `/login` for pages.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Liveness. The only public route besides login. |
| `GET` | `/login` | Password page. |
| `POST` | `/login` | Check the password, start a session. |
| `POST` | `/logout` | End the session. |
| `GET` | `/` | The game. |
| `POST` | `/api/games` | Start a game. |
| `GET` | `/api/games/{id}` | Current board, for resuming a reload. |
| `POST` | `/api/games/{id}/guesses` | Score a guess. |

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
`"Not in word list"`, `"Guess must be 5 letters"` or `"Guess must contain
letters only"`. A rejected guess costs no attempt. `409` means the game is over,
`404` that it expired or never existed.

## Word list

`backend/wordle/data/words.csv`, one word per row under a `word` header. Every
row must be a five-letter alphabetic word; a bad row stops startup with the
offending line number rather than being quietly skipped.

Swapping in a database means reimplementing `WordRepository` and nothing else.

## Known limits

- **Games live in memory**, so run exactly one worker. A second worker would not
  see games created by the first. Moving to Redis means implementing the
  `GameStore` protocol.
- **The login throttle is per process** — a speed bump, not a real rate limit.
  Put one at the reverse proxy for an internet-facing deployment.
- **One shared password**, no accounts. Everyone who has it sees the same site.
