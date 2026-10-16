#!/bin/sh
set -u

# Render sets $PORT automatically. Fall back to 8080 for other platforms.
: "${PORT:=8080}"

echo "ENTRYPOINT START: $(date)"
trap 'echo "ENTRYPOINT EXIT: status=$? at $(date)"' EXIT

if python manage.py migrate --noinput; then
    echo "Migrations completed"
else
    echo "Migrations failed; continuing so the app can still serve health checks"
fi

if python manage.py collectstatic --noinput --clear; then
    echo "Collectstatic completed"
else
    echo "Collectstatic failed; continuing"
fi

echo "Starting gunicorn on port ${PORT}"
exec python -m gunicorn micro_mentor.wsgi:application \
    --bind 0.0.0.0:${PORT} \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    --log-level info
