#!/bin/bash

# ==============================================================================
# Binance Grid Bot - Ubuntu/Linux Startup Script
# ==============================================================================

export PYTHONIOENCODING=utf-8

echo "[1/3] Checking environment..."

# 检查 .env 配置文件
if [ ! -f ".env" ]; then
    echo "[ERROR] .env file not found!"
    echo "Please copy .env.example to .env and fill in your API keys."
    exit 1
fi

# 检查 Python 命令 (优先使用 python3)
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "[ERROR] Python 3 not found. Please install Python 3."
    exit 1
fi

echo "[2/3] Found Python executable: $($PYTHON_CMD --version)"

echo "[3/3] Starting bot..."
echo "------------------------------------------------------------"

echo "[3.1/3] Running pre-flight cleanup..."
$PYTHON_CMD cleanup.py

echo "[3.2/3] Starting bot engine..."
$PYTHON_CMD main.py

exit_code=$?
if [ $exit_code -ne 0 ]; then
    echo "------------------------------------------------------------"
    echo "[WARNING] Bot stopped with exit code: $exit_code"
fi

echo "------------------------------------------------------------"
echo "Done."
