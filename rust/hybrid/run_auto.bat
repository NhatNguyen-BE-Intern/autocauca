@echo off
setlocal enabledelayedexpansion
title NomStead Auto Fishing - Infinite Loop Mode
color 0B

echo ================================================================
echo       NOMSTEAD HYBRID RUST/PYTHON AUTONOMOUS FISHING TOOL
echo ================================================================
echo.

cd /d "%~dp0"

:: 1. Kiem tra cong Chrome Debug 9222
echo [1/3] Kiem tra ket noi Chrome Remote Debugging (port 9222)...
netstat -ano | findstr :9222 >nul
if %errorlevel% neq 0 (
    echo [CANH BAO] Khong tim thay Chrome dang chay tren cong 9222!
    if exist "start_chrome_debug.bat" (
        echo Dang khoi dong Chrome Debug tu dong...
        start "" "start_chrome_debug.bat"
        timeout /t 3 /nobreak >nul
    ) else if exist "..\..\python\start_chrome_debug.bat" (
        echo Dang khoi dong Chrome Debug tu dong...
        start "" "..\..\python\start_chrome_debug.bat"
        timeout /t 3 /nobreak >nul
    ) else (
        echo Vui long chay start_chrome_debug.bat truoc de mo game tren Chrome Debug!
        pause
        exit /b 1
    )
) else (
    echo [OK] Chrome Debug port 9222 da san sang.
)

:: 2. Nhap so ho bat dau
echo.
echo [2/3] Cau hinh phien cau ca:
set /p START_LAKE="Nhap so ho bat dau [1-40] (Nhan Enter de dung mac dinh ho 1): "
if "%START_LAKE%"=="" set START_LAKE=1

:: Kiem tra hop le ho
if %START_LAKE% lss 1 (
    set START_LAKE=1
)
if %START_LAKE% gtr 40 (
    set START_LAKE=40
)

:: 3. Chay Auto Loop
echo.
echo [3/3] Dang khoi dong Vong lap Treo Game Bat tan...
echo ----------------------------------------------------------------
echo Ho bat dau : Ho %START_LAKE%
echo Che do     : Auto Loop 40 Ho (Co che hoi phuc Banh mi + Watchdog)
echo Huong dan  : Nhan Ctrl+C de DUNG TOOL AN TOAN bat cu luc nao.
echo ----------------------------------------------------------------
echo.

python -u bridge.py --auto --lake %START_LAKE%

echo.
echo ================================================================
echo Phien cau ca da ket thuc an toan.
echo ================================================================
pause
