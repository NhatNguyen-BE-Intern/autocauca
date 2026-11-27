@echo off
setlocal
title Chrome Debug 9222 - NomStead

set "CHROME_BIN="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set "CHROME_BIN=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not defined CHROME_BIN if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set "CHROME_BIN=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not defined CHROME_BIN if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME_BIN=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if not defined CHROME_BIN (
    echo [LOI] Khong tim thay Google Chrome tren may!
    pause
    exit /b 1
)

set "BG_FLAGS="
set "MODE_LABEL=VM / Foreground Stealth (Khuyen nghi)"
if /i "%~1"=="--bg" (
    set "BG_FLAGS=--disable-background-timer-throttling --disable-backgrounding-occluded-windows --disable-renderer-backgrounding"
    set "MODE_LABEL=Background / Occluded Mode (--bg)"
)

echo ========================================================
echo DANG KHOI DONG CHROME DEBUG CHO NOMSTEAD
echo ========================================================
echo Chrome: "%CHROME_BIN%"
echo Port  : 9222
echo Mode  : %MODE_LABEL%
if defined BG_FLAGS (
    echo [CANH BAO] Dang bat co chay nen ^(--bg^). Chi dung khi de cua so Chrome bi che tren may chinh.
) else (
    echo [STEALTH] Mac dinh khong bat co background-throttling; dung "start_chrome_debug.bat --bg" neu can chay an sau cua so khac.
)
echo.

start "" "%CHROME_BIN%" --remote-debugging-port=9222 --user-data-dir="%~dp0chrome_debug_profile" %BG_FLAGS% --mute-audio --no-first-run --no-default-browser-check --disable-sync --disable-translate --disable-component-update --disable-background-networking --disable-default-apps --disable-features=Translate,MediaRouter,OptimizationHints --js-flags="--max-old-space-size=1024" "https://nomstead.com"

echo [OK] Da mo Chrome thanh cong!
echo Hay dang nhap game tren cua so Chrome do.
echo ========================================================
pause
