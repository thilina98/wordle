# Secrets

None are needed at the moment. The shared game password and the token-signing
key were removed: anyone can play. If you still have `wordle_password` and
`wordle_secret_key` here, they are unused and can be deleted.

When a secret is added, it goes here as one file, named after its setting,
holding just the value — no `KEY=` prefix, no quotes. The app reads this
directory whether or not it is in Docker — `/run/secrets` inside a container,
`secrets/` when run from source.

**Secrets belong here and nowhere else.** Never in `.env`: that file is read by
Docker Compose, so a secret in it becomes a container environment variable,
and `docker inspect` prints those.

Everything here except this README is gitignored.
