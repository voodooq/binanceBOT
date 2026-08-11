@echo off
SETLOCAL EnableDelayedExpansion

chcp 65001 >nul
set PYTHONIOENCODING=utf-8

TITLE BinanceBot V3 Local Dev

set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

echo [1/5] Checking environment...

IF NOT EXIST ".env" (
    echo [ERROR] .env file not found!
    echo Please copy .env.example to .env and fill in the required values.
    pause
    exit /b 1
)

set "CONDA_PATH=D:\anaconda3"
set "ENV_NAME=binancebot"
set "ACTIVATE_BAT=%CONDA_PATH%\Scripts\activate.bat"

echo [2/5] Activating Conda env: %ENV_NAME%...

IF NOT EXIST "%ACTIVATE_BAT%" (
    echo [ERROR] Conda activate script not found: %ACTIVATE_BAT%
    pause
    exit /b 1
)

call "%ACTIVATE_BAT%" %ENV_NAME%
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to activate Conda env: %ENV_NAME%
    pause
    exit /b 1
)

echo [3/5] Running database migrations...
python -m alembic upgrade head
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Alembic migration failed.
    echo         Please confirm PostgreSQL/Redis are available and .env is configured correctly.
    pause
    exit /b 1
)

echo [4/5] Starting frontend dev server...
IF NOT EXIST "frontend\node_modules" (
    echo [WARNING] frontend\node_modules not found.
    echo           Please run: cd frontend ^&^& npm install
) ELSE (
    where npm >nul 2>nul
    IF %ERRORLEVEL% EQU 0 (
        start "BinanceBot Frontend" cmd /k "cd /d ""%PROJECT_ROOT%frontend"" && npm run dev"
    ) ELSE (
        echo [WARNING] npm not found in PATH. Frontend dev server was not started.
    )
)

echo [5/5] Starting backend API...
echo ------------------------------------------------------------
echo Frontend ^(Vite^): http://127.0.0.1:5173
echo Backend API:      http://127.0.0.1:8000
echo Swagger:          http://127.0.0.1:8000/api/v1/openapi.json
echo Press Ctrl+C to stop the backend server.
echo ------------------------------------------------------------

python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

set "EXIT_CODE=%ERRORLEVEL%"
IF %EXIT_CODE% NEQ 0 (
    echo ------------------------------------------------------------
    echo [WARNING] Backend stopped with exit code: %EXIT_CODE%
    pause
    exit /b %EXIT_CODE%
)

echo ------------------------------------------------------------
echo Done.
pause