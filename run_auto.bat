@echo off
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
title Auto Cau Ca NomStead - 40 Bookmarks Tự Động

echo ================================================================
echo        TOOL AUTO CÂU CÁ NOMSTEAD (40 BOOKMARKS TOÀN DIỆN)
echo ================================================================
echo.
echo [LƯU Ý QUAN TRỌNG TRƯỚC KHI CHẠY]
echo 1. Hãy mở game NomStead trên trình duyệt Chrome/Edge.
echo 2. Đặt tỷ lệ thu phóng trình duyệt chuẩn 100%% (bấm Ctrl + 0).
echo 3. Giữ cửa sổ game hiển thị trên màn hình chính (không thu nhỏ).
echo 4. Nhấn giữ phím 'Q' bất cứ lúc nào để DỪNG TOOL an toàn.
echo.
echo ================================================================
echo.

where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [LỖI] Không tìm thấy Python trong hệ thống!
    echo Vui lòng cài đặt Python 3.10+ và tích chọn "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

echo [OK] Đang khởi chạy auto_fish.py...
echo.
python auto_fish.py

echo.
echo ================================================================
echo Chương trình đã kết thúc hoặc được người dùng tạm dừng.
echo ================================================================
echo.
pause
