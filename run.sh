#!/bin/bash

# ==============================================================================
# BinanceBot V3 - Local Development Startup Script
# ==============================================================================

export PYTHONIOENCODING=utf-8

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

FRONTEND_PID=""

cleanup() {
    if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
        kill "$FRONTEND_PID" >/dev/null 2>&1 || true
    fi
}

trap cleanup EXIT

echo "[1/5] Checking environment..."

if [ ! -f ".env" ]; then
    echo "[ERROR] .env file not found!"
    echo "Please copy .env.example to .env and fill in the required values."
    exit 1
fi

if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
else
    echo "[ERROR] Python 3 not found. Please install Python 3."
    exit 1
fi

echo "[2/5] Found Python executable: $($PYTHON_CMD --version)"

echo "[3/5] Running database migrations..."
if ! $PYTHON_CMD -m alembic upgrade head; then
    echo "[ERROR] Alembic migration failed."
    echo "        Please confirm PostgreSQL/Redis are available and .env is configured correctly."
    exit 1
fi

echo "[4/5] Starting frontend dev server..."
if [ ! -d "frontend/node_modules" ]; then
    echo "[WARNING] frontend/node_modules not found."
    echo "          Please run: cd frontend && npm install"
else
    if command -v npm >/dev/null 2>&1; then
        (
            cd frontend
            npm run dev
        ) &
        FRONTEND_PID=$!
    else
        echo "[WARNING] npm not found in PATH. Frontend dev server was not started."
    fi
fi

echo "[5/5] Starting backend API..."
echo "------------------------------------------------------------"
echo "Frontend (Vite): http://127.0.0.1:5173"
echo "Backend API:     http://127.0.0.1:8000"
echo "Swagger:         http://127.0.0.1:8000/api/v1/openapi.json"
echo "Press Ctrl+C to stop the backend server."
echo "------------------------------------------------------------"

$PYTHON_CMD -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
exit_code=$?

if [ $exit_code -ne 0 ]; then
    echo "------------------------------------------------------------"
    echo "[WARNING] Backend stopped with exit code: $exit_code"
    exit $exit_code
fi

echo "------------------------------------------------------------"
echo "Done."