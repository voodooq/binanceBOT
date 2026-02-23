@echo off
SETLOCAL EnableDelayedExpansion

chcp 65001 >nul
set PYTHONIOENCODING=utf-8

TITLE Binance Grid Bot - Backtester v2

SET CONDA_PATH=D:\anaconda3
SET ENV_NAME=binancebot

echo ============================================================
echo   Binance MarketAnalyzer Backtester v2
echo   Features: State Heatmap / Panic Slippage / Equity Curve
echo ============================================================
echo.

IF NOT EXIST "%CONDA_PATH%\Scripts\activate.bat" (
    echo [ERROR] Conda not found at %CONDA_PATH%
    pause
    exit /b 1
)

call "%CONDA_PATH%\Scripts\activate.bat" %ENV_NAME%

:MENU
echo.
echo Select backtest parameters (press Enter for defaults):
echo ------------------------------------------------------------
set /p SYMBOL="Symbol (default BNBUSDT): "
if "!SYMBOL!"=="" set SYMBOL=BNBUSDT

set /p DAYS="Days (default 30): "
if "!DAYS!"=="" set DAYS=30

set /p INTERVAL="Interval [1h/15m/5m] (default 1h): "
if "!INTERVAL!"=="" set INTERVAL=1h

set /p SLIPPAGE="Panic slippage [0.003=0.3%%] (default 0.003): "
if "!SLIPPAGE!"=="" set SLIPPAGE=0.003

set /p FEE="Fee rate [0.001=0.1%%] (default 0.001): "
if "!FEE!"=="" set FEE=0.001

echo.
echo  Parameters:
echo    Symbol:   !SYMBOL!
echo    Days:     !DAYS!
echo    Interval: !INTERVAL!
echo    Slippage: !SLIPPAGE!
echo    Fee:      !FEE!
echo ------------------------------------------------------------

python -m src.strategies.backtester --symbol !SYMBOL! --days !DAYS! --interval !INTERVAL! --slippage !SLIPPAGE! --fee !FEE!

echo.
echo ------------------------------------------------------------
set /p CONTINUE="Run another backtest? (y/n, default n): "
if /i "!CONTINUE!"=="y" (
    cls
    goto MENU
)

pause
