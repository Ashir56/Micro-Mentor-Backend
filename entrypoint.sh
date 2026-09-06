#!/bin/sh
set -u

# Default to 8080 if PORT not provided by host
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
    echo "Collectstatic failed; continuing so the app can still start"
fi

# Debugging output to help diagnose startup issues in logs
set -x
echo "Starting app with PORT=${PORT}"
echo "Python: $(python --version 2>&1)"
echo "Gunicorn (via python -m) available:"
python -m pip show gunicorn || true

exec python -m gunicorn micro_mentor.wsgi:application --bind 0.0.0.0:${PORT} --workers 3 --access-logfile - --log-level debug
