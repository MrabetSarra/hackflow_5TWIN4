#!/bin/sh
set -eu

# Match the production defaults in hackflow/settings.py while honoring explicit paths.
DATABASE_PATH=${DATABASE_PATH:-"$PWD/db.sqlite3"}
MEDIA_ROOT=${MEDIA_ROOT:-/tmp/media/uploads}
PRIVATE_MEDIA_ROOT=${PRIVATE_MEDIA_ROOT:-/tmp/private_media}
HACKFLOW_REPOS_ROOT=${HACKFLOW_REPOS_ROOT:-/tmp/.repository-data}
STATIC_ROOT=${STATIC_ROOT:-"$PWD/staticfiles"}

mkdir -p \
  "$(dirname "$DATABASE_PATH")" \
  "$MEDIA_ROOT" \
  "$PRIVATE_MEDIA_ROOT" \
  "$HACKFLOW_REPOS_ROOT" \
  "$STATIC_ROOT"

python manage.py migrate --noinput
python manage.py ensure_admin

if [ "${SEED_DEMO:-0}" = "1" ]; then
  python manage.py seed_demo
  if command -v git >/dev/null 2>&1; then
    python manage.py seed_repositories
  else
    printf '%s\n' 'WARNING: Git is unavailable; skipping optional demo repository seed.'
  fi
fi

PORT=${PORT:-10000}
export PORT
exec gunicorn hackflow.wsgi:application --bind "0.0.0.0:$PORT" --workers 2 --timeout 120
