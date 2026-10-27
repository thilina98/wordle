# Secrets

One file, one secret. The file contents are the whole secret — no `KEY=`
prefix, no quotes.

| File | What it is |
|---|---|
| `wordle_database_password` | Password for the PostgreSQL `wordle` user. The `db` container sets it on first start; the API reads it to connect. |
| `wordle_auth0_deletion_app_client_secret` | Client Secret of the Auth0 deletion app (Machine to Machine), from that app's Settings tab. Required when `WORDLE_AUTH_PROVIDER=auth0`. The file must exist for Docker to start either way. |

Create it:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32), end='')" > secrets/wordle_database_password
printf "%s" "PASTE_DELETION_APP_CLIENT_SECRET" > secrets/wordle_auth0_deletion_app_client_secret
chmod 600 secrets/wordle_*
```

The app reads this directory whether or not it is in Docker — `/run/secrets`
inside a container, `secrets/` when run from source. **Secrets belong here and
nowhere else.** Never in `backend/.env` or `frontend/.env`: Docker Compose
hands those to the containers as environment variables, and `docker inspect`
prints those.

PostgreSQL only reads the password when it creates a fresh database. Changing
the file afterwards also needs `ALTER USER wordle PASSWORD '...'` inside the
database, or the API will be locked out.

There is no shared game password and no token-signing key any more: sign-in is
done by an identity provider, which signs the tokens itself. The old
`wordle_password` and `wordle_secret_key` files are unused and can be deleted.

Everything here except this README is gitignored.
