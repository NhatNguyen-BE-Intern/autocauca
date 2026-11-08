@echo off
chcp 65001 > nul
cd /d "%~dp0"
title Auto Fish NomStead v2.0

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [LỖI] Không tìm thấy Python trong PATH của Windows!
    echo Vui lòng cài đặt Python và tích chọn "Add Python to PATH".
    pause
    exit /b 1
)

python auto_fish.py
if %errorlevel% neq 0 (
    echo.
    echo [LƯU Ý] Quá trình kết thúc với mã lỗi: %errorlevel%
)
pause
