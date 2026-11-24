@echo off
title Cai dat moi truong May Ao (VM Setup)
color 0A
echo ========================================================
echo        CAI DAT MOI TRUONG CHO MAY AO (VM)
echo ========================================================
echo.

:: 0. Kiem tra goi Python Portable (Zero-Install)
if exist "%~dp0python_embed\python.exe" (
    "%~dp0python_embed\python.exe" -c "import cv2, numpy, PIL, websockets" >nul 2>&1
    if not errorlevel 1 (
        echo [OK] Goi Python Portable ^(python_embed\^) da duoc tich hop san va san sang chay!
        echo Ban KHONG can cai dat Python hay pip tren May Ao nay.
        echo.
        echo Cach su dung:
        echo 1. Chay rust\hybrid\start_chrome_debug.bat de mo game.
        echo 2. Dang nhap game va vao nhan vat.
        echo 3. Chay rust\hybrid\run_auto.bat de bat dau treo ca!
        echo ========================================================
        pause
        exit /b 0
    )
)

:: 1. Kiem tra Python he thong (Fallback khi khong co python_embed)
python --version >nul 2>&1
if errorlevel 1 (
    echo [LOI] May ao chua cai Python va khong tim thay goi python_embed\!
    echo Vui long tai va cai Python tu: https://www.python.org/downloads/
    echo (Luu y: Nho tich chon "Add Python to PATH" khi cai dat)
    pause
    exit /b 1
)

echo [1/2] Da tim thay Python:
python --version
echo.

:: 2. Cai dat cac thu vien can thiet
echo [2/2] Dang cai dat cac goi thu vien nhe (OpenCV Headless, NumPy, Pillow, WebSockets)...
python -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo [CANH BAO] Cai dat bang requirements.txt gap loi, dang thu cai truc tiep...
    python -m pip install opencv-python-headless numpy pillow websockets
)

echo.
echo ========================================================
echo [OK] DA HOAN TAT CAI DAT CHO MAY AO!
echo (Ban KHONG can cai Rust hay Visual Studio)
echo.
echo Cach su dung:
echo 1. Chay start_chrome_debug.bat de mo game.
echo 2. Dang nhap game va vao nhan vat.
echo 3. Chay run_auto.bat de bat dau treo ca!
echo ========================================================
pause

