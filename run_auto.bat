@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
title Auto Cau Ca NomStead - 40 Bookmarks

echo ======================================================
echo       TOOL AUTO CAU CA NOMSTEAD (40 BOOKMARKS)
echo ======================================================
echo.

where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [LOI] Khong tim thay Python trong he thong!
    echo Vui long cai dat Python va them vao PATH.
    pause
    exit /b 1
)

echo Dang khoi chay auto_fish.py...
echo.
python auto_fish.py

echo.
echo ======================================================
echo Chuong trinh da ket thuc hoac bi dung.
echo ======================================================
pause
