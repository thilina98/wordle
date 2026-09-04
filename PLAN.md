# Wordle — Implementation Plan

Five-letter word game, five attempts, colour-coded feedback. Mobile-first,
physical + on-screen keyboard. Whole site behind a shared password.

## Architecture

Backend owns every game rule. The frontend is a view layer: it renders what the
API returns and never decides a colour. This is deliberate — it keeps the answer
off the client and means one tested implementation of the rules, not two.

```
browser ──HTTP──> FastAPI
                    ├── page routes  (/, /login)   session-gated HTML
                    ├── /static/*                  session-gated assets
                    └── /api/*                     session-gated JSON
                          └── domain: game logic, word repository, game store
```

### Layout

    backend/
      wordle/
        config.py     Settings from environment (pydantic-settings)
        game.py       Pure rules: evaluate_guess, GameState. No I/O, no framework.
        words.py      WordRepository over CSV. Swappable for a DB later.
        store.py      GameStore protocol + in-memory impl with TTL eviction.
        security.py   Password check, login throttle, auth dependency.
        schemas.py    Request/response models.
        api.py        /api router.
        app.py        App factory, page routes, static mount.
        data/words.csv
      tests/          test_game, test_words, test_store, test_security, test_api
    frontend/
      login.html  index.html  app.js  style.css

## Access control

A shared password, no users. `POST /login` compares against
`WORDLE_PASSWORD` with `hmac.compare_digest` and sets a signed session cookie
(`itsdangerous`, via Starlette's `SessionMiddleware`). Everything else — the game
page, the CSS, the JS, every API route — requires that cookie. Unauthenticated
page requests redirect to `/login`; unauthenticated API requests get 401.

The password never reaches client-side JavaScript. Failed logins are throttled
per client IP.

## Testing

TDD: tests first, then the implementation, per step below. Tests assert
input/output contracts — `evaluate_guess("crane", "caner")` returns a specific
colour list; `POST /api/guess` returns a specific shape — so they survive
refactoring of the internals.

No Node runtime is available on this machine, so there is no JS test suite.
Shipping one that cannot run would be worse than not having it. The mitigation is
architectural: the frontend holds no game rules to test.

## Steps

Each step is one commit, tests written before the code.

1. Teardown, plan, gitignore.
2. Poetry project, modern pins, Python 3.13 venv.
3. `game.py` — colour evaluation incl. duplicate letters, attempt tracking.
4. `words.py` — CSV loading, validation, random selection.
5. `store.py` — game persistence with TTL eviction.
6. `security.py` — password verification, throttling, auth dependency.
7. `api.py` + `app.py` — endpoints, session gate, static serving.
8. Frontend — grid, keyboards, colour reveal, mobile layout.
9. README, `.env.example`, final review pass.

## Deferred

Word list stays CSV; the `WordRepository` seam is where a DB goes. Game store is
in-memory; the `GameStore` protocol is where Redis goes.
