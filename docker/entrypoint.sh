#!/bin/sh
set -e

mkdir -p /app/data

case "${RUN_STARTUP_TASKS:-false}" in
  true|True|TRUE|1|yes|Yes|YES)
    python manage.py migrate --noinput
    python manage.py ensure_default_admin
    python manage.py collectstatic --noinput
    ;;
esac

exec "$@"
