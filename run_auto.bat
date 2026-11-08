@echo off
cd /d "%~dp0"
title NomStead Auto Fishing

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not found in system PATH!
    echo Please install Python and check "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

python auto_fish.py
if %errorlevel% neq 0 (
    echo.
    echo Tool finished with code: %errorlevel%
)
pause
