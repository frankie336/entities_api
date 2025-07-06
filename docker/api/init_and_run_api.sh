#!/usr/bin/env bash
# Runs Alembic migrations, then starts the main command (Supervisor)
set -e

# The wait-for-it.sh line is GONE. Python handles it now.

# Auto-migrate when flag is on
if [ "$AUTO_MIGRATE" = "1" ]; then
  echo "🗄️  Running Alembic migrations…"
  alembic upgrade head
fi

echo "🚀 Starting Supervisor (which will run Uvicorn)…"
exec "$@"