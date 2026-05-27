#!/bin/sh
set -e

mkdir -p /app/data

python manage.py migrate --noinput
python manage.py ensure_default_admin
python manage.py collectstatic --noinput

exec "$@"
