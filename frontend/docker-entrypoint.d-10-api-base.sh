#!/bin/sh
# Point the frontend at the API. Runs before nginx starts, on every boot.
#
# Written to /tmp, not the web root: the container runs with a read-only root
# filesystem, and /tmp is the tmpfs. nginx serves it via an alias.
set -eu
: "${WORDLE_API_BASE:=http://localhost:8000}"
cat > /tmp/config.js <<JS
window.WORDLE_CONFIG = { apiBase: '${WORDLE_API_BASE}' };
JS
echo "frontend: API base set to ${WORDLE_API_BASE}"
