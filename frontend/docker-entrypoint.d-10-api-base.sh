#!/bin/sh
# Write config.js from frontend/.env. Runs before nginx starts, on every boot.
#
# Written to /tmp, not the web root: the container runs with a read-only root
# filesystem, and /tmp is the tmpfs. nginx serves it via an alias.
set -eu
: "${WORDLE_API_BASE:=http://localhost:8000}"
: "${WORDLE_AUTH_ISSUER:=}"
: "${WORDLE_AUTH_LOGIN_APP_CLIENT_ID:=}"
: "${WORDLE_AUTH_AUDIENCE:=}"

# Sign-in needs all three values or none. Half a configuration is a mistake:
# refuse to start rather than show a sign-in button that cannot work.
set_count=0
for value in "$WORDLE_AUTH_ISSUER" "$WORDLE_AUTH_LOGIN_APP_CLIENT_ID" "$WORDLE_AUTH_AUDIENCE"; do
  [ -n "$value" ] && set_count=$((set_count + 1))
done
if [ "$set_count" -ne 0 ] && [ "$set_count" -ne 3 ]; then
  echo "frontend: set all of WORDLE_AUTH_ISSUER, WORDLE_AUTH_LOGIN_APP_CLIENT_ID and" \
       "WORDLE_AUTH_AUDIENCE in frontend/.env, or none of them" >&2
  exit 1
fi

if [ "$set_count" -eq 3 ]; then
  auth="{ issuer: '${WORDLE_AUTH_ISSUER}', clientId: '${WORDLE_AUTH_LOGIN_APP_CLIENT_ID}', audience: '${WORDLE_AUTH_AUDIENCE}' }"
  echo "frontend: sign-in on, issuer ${WORDLE_AUTH_ISSUER}"
else
  auth="null"
  echo "frontend: sign-in off"
fi

cat > /tmp/config.js <<JS
window.WORDLE_CONFIG = { apiBase: '${WORDLE_API_BASE}', auth: ${auth} };
JS
echo "frontend: API base set to ${WORDLE_API_BASE}"
