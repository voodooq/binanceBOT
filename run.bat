@echo off
SETLOCAL EnableDelayedExpansion

chcp 65001 >nul
set PYTHONIOENCODING=utf-8

TITLE Binance Grid Bot

echo [1/3] Checking environment...

IF NOT EXIST ".env" (
    echo [ERROR] .env file not found!
    echo Please copy .env.example to .env and fill in your API keys.
    pause
    exit /b 1
)

SET CONDA_PATH=D:\anaconda3
SET ENV_NAME=binancebot

echo [2/3] Activating Conda env: %ENV_NAME%...

IF NOT EXIST "%CONDA_PATH%\Scripts\activate.bat" (
    echo [ERROR] Conda not found at %CONDA_PATH%
    pause
    exit /b 1
)

echo [3/3] Starting bot...
echo ------------------------------------------------------------

call "%CONDA_PATH%\Scripts\activate.bat" %ENV_NAME%
echo [3.1/3] Running pre-flight cleanup...
python cleanup.py
echo [3.2/3] Starting bot engine...
python main.py

IF %ERRORLEVEL% NEQ 0 (
    echo ------------------------------------------------------------
    echo [WARNING] Bot stopped with exit code: %ERRORLEVEL%
    pause
)

echo ------------------------------------------------------------
echo Done.
pause
