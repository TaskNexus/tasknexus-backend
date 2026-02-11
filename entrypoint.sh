#!/bin/bash
set -e

# Waiting for database... (handled by docker-compose healthcheck, but good to have)
# python manage.py wait_for_db # Optional custom command if you have one

echo "Applying database migrations..."
python manage.py migrate

echo "Starting server..."
exec "$@"
