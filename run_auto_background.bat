@echo off
chcp 65001 >nul
title Auto Fish Nomstead - Background Mode
cd /d "%~dp0"

echo ========================================================
echo       AUTO FISH NOMSTEAD - CHAY NGAM (KHONG CHIEM CHUOT)
echo ========================================================
echo.

netstat -ano | findstr "9222" >nul
if errorlevel 1 (
    echo [CANH BAO] Chua phat hien Chrome tren cong 9222!
    echo Dang khoi dong Chrome...
    call start_chrome_debug.bat
    timeout /t 3 >nul
)

echo Dang khoi dong auto_fish_background.py ...
echo.
python auto_fish_background.py

echo.
echo ========================================================
echo Tool da dung.
echo ========================================================
pause
