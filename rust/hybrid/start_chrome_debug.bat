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

echo ========================================================
echo DANG KHOI DONG CHROME DEBUG CHO NOMSTEAD
echo ========================================================
echo Chrome: "%CHROME_BIN%"
echo Port  : 9222
echo.

start "" "%CHROME_BIN%" --remote-debugging-port=9222 --user-data-dir="%~dp0chrome_debug_profile" --disable-background-timer-throttling --disable-backgrounding-occluded-windows --disable-renderer-backgrounding --mute-audio --no-first-run --no-default-browser-check --disable-extensions --disable-sync --disable-translate --disable-component-update --disable-background-networking --disable-default-apps --no-pings --disable-features=Translate,BackForwardCache,MediaRouter,OptimizationHints --js-flags="--max-old-space-size=1024" "https://nomstead.com"

echo [OK] Da mo Chrome thanh cong!
echo Hay dang nhap game tren cua so Chrome do.
echo Ban co the de no chay ngam ma khong lo bi mat chuot.
echo ========================================================
pause
