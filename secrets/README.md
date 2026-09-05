# Secrets

One secret per file, the file contents being the whole secret — no `KEY=`
prefix, no quotes, no trailing newline needed.

Docker Compose mounts these at `/run/secrets/<name>` inside the API container,
and the app reads them by filename. Environment variables would work too, but
`docker inspect` and `/proc/<pid>/environ` both show the environment; neither
shows these.

Create them:

```bash
printf '%s' 'the-password-you-will-share' > secrets/wordle_password
python3 -c "import secrets; print(secrets.token_urlsafe(32), end='')" > secrets/wordle_secret_key
chmod 600 secrets/wordle_*
```

Everything here except this README is gitignored. Never commit a real secret.
