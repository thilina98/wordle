#!/bin/sh
# Point the frontend at the API. Runs before nginx starts, on every boot.
set -eu
: "${WORDLE_API_BASE:=http://localhost:8000}"
cat > /usr/share/nginx/html/config.js <<JS
window.WORDLE_CONFIG = { apiBase: '${WORDLE_API_BASE}' };
JS
echo "frontend: API base set to ${WORDLE_API_BASE}"
