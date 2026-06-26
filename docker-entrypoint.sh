#!/bin/bash
set -e

echo "Environment: $FLASK_ENV"
echo "Database URL: ${DATABASE_URL:0:20}..." # Show only first 20 chars for security

# Check if DATABASE_URL is set
if [ -z "$DATABASE_URL" ]; then
    echo "ERROR: DATABASE_URL not set. Railway should provide this automatically."
    exit 1
fi

# Check if SECRET_KEY is set in production
if [ "$FLASK_ENV" = "production" ] && [ -z "$SECRET_KEY" ]; then
    echo "ERROR: SECRET_KEY not set. Set it in Railway environment variables."
    exit 1
fi

echo "Running database migrations..."
flask db upgrade

echo "Seeding default data (if empty)..."
flask seed-data

echo "Starting application..."
exec gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 2 --timeout 120 --access-logfile - --error-logfile - "run:app"
