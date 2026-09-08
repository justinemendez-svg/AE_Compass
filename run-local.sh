#!/bin/bash
# AE Compass — local launcher (no Postgres/Snowflake).
# Starts the local data adapter (:8080) and the Vite frontend (:5173) together.
# Ctrl-C stops both. Nothing here touches the real database or GitHub.
set -e
cd "$(dirname "$0")"

echo "Starting AE Compass local playground…"

# Mock data server. Override AE_COMPASS_API_PORT if another local preview is using 8080.
API_PORT="${AE_COMPASS_API_PORT:-8080}"
PORT="$API_PORT" python3 server/mock_server.py &
SERVER_PID=$!

# Make sure we kill the server when this script exits
trap "echo; echo 'Shutting down…'; kill $SERVER_PID 2>/dev/null" EXIT INT TERM

sleep 1
echo "→ Open http://localhost:5173 in your browser"

# Frontend (foreground — Ctrl-C here stops everything)
AE_COMPASS_API_PORT="$API_PORT" npm run dev
