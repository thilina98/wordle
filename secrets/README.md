# Secrets

Two files, one secret each. The file contents are the whole secret — no
`KEY=` prefix, no quotes.

| File | What it is |
|---|---|
| `wordle_password` | What a player types to get in |
| `wordle_secret_key` | Signs the login token. Nobody ever types it. |

Two, not one, because the jobs conflict. The password has to be short enough
for a person to type. The signing key has to survive an offline attack: anyone
who captures a token can guess against it on their own machine, with no
rate limit, so it needs real randomness.

Create them:

```bash
printf '%s' 'the-password-you-will-share' > secrets/wordle_password
python3 -c "import secrets; print(secrets.token_urlsafe(32), end='')" > secrets/wordle_secret_key
chmod 600 secrets/wordle_*
```

The app reads this directory whether or not it is in Docker — `/run/secrets`
inside a container, `secrets/` when run from source. **Secrets belong here and
nowhere else.** Never in `.env`: that file is read by Docker Compose, so a
secret in it becomes a container environment variable, and `docker inspect`
prints those.

Changing `wordle_password` means new logins need the new one. Changing
`wordle_secret_key` logs everyone out at once, because every existing token
stops verifying.

Everything here except this README is gitignored.
