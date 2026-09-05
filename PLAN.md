# Wordle — Implementation Plan

Five-letter word game, five attempts, colour-coded feedback. Mobile-first,
physical + on-screen keyboard. Protected by a shared password.

## Architecture

One repository, two applications, built and run separately. They share nothing
but the HTTP contract.

```
browser ──▶ frontend (static files + web server, port 8080)
        │       index.html  style.css  app.js  api.js  config.js
        │
        └──▶ backend (FastAPI, port 8000)   JSON only, no HTML
                 api.py    routes, token gate, CORS
                 game.py   the rules. no I/O, no framework
                 words.py  WordRepository over CSV
                 store.py  GameStore protocol + in-memory impl
```

The backend owns every game rule. The frontend renders what the API returns and
never decides a colour. That keeps the answer off the client and means one
tested implementation of the rules, not two.

### Layout

    backend/
      Dockerfile
      wordle/
        config.py     Settings from environment (pydantic-settings)
        game.py       Pure rules: evaluate_guess, GameState
        words.py      WordRepository over CSV. Swappable for a DB later.
                      Two lists: answers (curated) and dictionary (all valid
                      guesses).
        store.py      GameStore protocol + in-memory impl with TTL eviction.
        security.py   Password check, login throttle, signed access tokens.
        schemas.py    Request/response models.
        api.py        Every route. /api/login plus the game routes.
        app.py        App factory, CORS. Serves no files.
        data/answers.csv, data/dictionary.csv
      tests/          test_game, test_words, test_store, test_security,
                      test_config, test_api
    frontend/
      Dockerfile      nginx, no build step
      nginx.conf
      index.html      password gate + game, one page
      api.js          the only file that knows the backend exists
      app.js          view layer
      style.css
      config.js       API base URL, rewritten at container start

## Access control

A shared password, no users. `POST /api/login` compares against
`WORDLE_PASSWORD` with `hmac.compare_digest` and returns a token signed with
`WORDLE_SECRET_KEY` and stamped with the time. Every game route requires it in
an `Authorization: Bearer` header.

A token rather than a cookie, because the two halves are separate origins.
A cross-origin cookie needs `SameSite=None; Secure`, which needs HTTPS, which
does not fit a bare-IP deployment over plain HTTP.

The frontend's files are public, since a separate static server hands them out.
They hold no password and no answers. The password gates playing, not
downloading an empty board.

Failed logins are throttled per client IP.

## Testing

TDD: tests first, then the implementation, per step below. Tests assert
input/output contracts — `evaluate_guess("crane", "caner")` returns a specific
colour list; `POST /api/games` returns a specific shape — so they survive
refactoring of the internals.

No Node runtime is available on this machine, so there is no JS test suite.
Shipping one that cannot run would be worse than not having it. The mitigation
is architectural: the frontend holds no game rules to test.

## Steps

Each step is one commit, tests written before the code.

1. Teardown, plan, gitignore.
2. Poetry project, modern pins, Python 3.13 venv.
3. `game.py` — colour evaluation incl. duplicate letters, attempt tracking.
4. `words.py` — CSV loading, validation, random selection.
5. `store.py` — game persistence with TTL eviction.
6. `security.py` — password verification, throttling.
7. `api.py` + `app.py` — endpoints, session gate.
8. Frontend — grid, keyboards, colour reveal, mobile layout.
9. README, `.env.example`, deployment guide.
10. Split the two halves apart: backend to JSON only, token auth and CORS,
    frontend onto its own web server with its own Dockerfile.

## Word lists

Answers come from a small curated list so nobody has to guess an obscure word.
Guesses are checked against a much larger dictionary so real words are never
refused. One list cannot do both jobs.

## Deferred

Word lists stay CSV; the `WordRepository` seam is where a DB goes. Game store is
in-memory; the `GameStore` protocol is where Redis goes.
