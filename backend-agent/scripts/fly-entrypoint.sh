#!/bin/sh
set -eu

mkdir -p /data/chroma /data/logs

echo "Running Alembic migrations..."
uv run alembic upgrade head

echo "Starting uvicorn (1 worker; WebSocket hub is in-process)..."
exec uv run uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips='*'
