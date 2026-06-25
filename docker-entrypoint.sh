#!/bin/sh
set -e

echo "Running database migrations..."
flask db upgrade || echo "Warning: db upgrade failed, continuing..."

echo "Starting application..."
exec gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 2 --timeout 120 "run:app"
