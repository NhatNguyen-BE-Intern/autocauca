@echo off
setlocal
title Dong goi AutoCauCa Portable
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_portable.ps1"
if errorlevel 1 (
    echo.
    echo [LOI] Dong goi that bai!
    pause
    exit /b 1
)
pause
