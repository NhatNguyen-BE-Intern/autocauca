param(
    [string]$PythonVersion = "3.13.15",
    [string]$OutputName = "AutoCauCa-Portable"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$HybridDir = Join-Path $RepoRoot "rust\hybrid"
$CacheDir = Join-Path $RepoRoot "build_cache"
$DistDir = Join-Path $RepoRoot "dist"
$PackageDir = Join-Path $DistDir $OutputName
$RuntimeDir = Join-Path $PackageDir "runtime"
$SitePackagesDir = Join-Path $RuntimeDir "Lib\site-packages"
$AppDir = Join-Path $PackageDir "app"
$AssetsDir = Join-Path $AppDir "assets"
$ZipOut = Join-Path $DistDir "$OutputName-Windows.zip"

$VerParts = $PythonVersion.Split(".")
$PyMajorMinor = "$($VerParts[0]).$($VerParts[1])"
$PyCompact = "$($VerParts[0])$($VerParts[1])"

$EmbedZipName = "python-$PythonVersion-embed-amd64.zip"
$EmbedZipUrl = "https://www.python.org/ftp/python/$PythonVersion/$EmbedZipName"
$EmbedZipPath = Join-Path $CacheDir $EmbedZipName

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  DONG GOI AUTO CAU CA PORTABLE (WINDOWS x64)" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

# 1. Verify source files
if (-not (Test-Path (Join-Path $HybridDir "bridge.py"))) {
    throw "Khong tim thay rust\hybrid\bridge.py"
}

New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null

# 2. Download official signed Python embeddable runtime (cached)
if (-not (Test-Path $EmbedZipPath)) {
    Write-Host "[1/5] Dang tai Python Embeddable $PythonVersion chinh chu tu python.org..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $EmbedZipUrl -OutFile $EmbedZipPath -UseBasicParsing
} else {
    Write-Host "[1/5] Su dung Python Embeddable $PythonVersion da cache."
}

# 3. Prepare clean package directory
Write-Host "[2/5] Dang chuan bi thu muc dong goi..."
if (Test-Path $PackageDir) {
    Remove-Item -Recurse -Force $PackageDir
}
if (Test-Path $ZipOut) {
    Remove-Item -Force $ZipOut
}

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $SitePackagesDir | Out-Null
New-Item -ItemType Directory -Force -Path $AssetsDir | Out-Null

Expand-Archive -Path $EmbedZipPath -DestinationPath $RuntimeDir -Force

# Configure ._pth so embeddable Python loads Lib\site-packages and ..\app
$PthFile = Join-Path $RuntimeDir "python$PyCompact._pth"
@(
    "python$PyCompact.zip"
    "."
    "Lib\site-packages"
    "..\app"
    "import site"
) | Set-Content -Path $PthFile -Encoding Ascii

# 4. Install pure binary wheels into portable site-packages
Write-Host "[3/5] Dang cai 4 thu vien (opencv-python-headless, numpy, pillow, websockets)..."
& python -m pip install `
    --no-user `
    --no-compile `
    --no-warn-script-location `
    --only-binary=:all: `
    --python-version $PyMajorMinor `
    --platform win_amd64 `
    --implementation cp `
    --abi "cp$PyCompact" `
    --target $SitePackagesDir `
    "opencv-python-headless>=4.8.0" `
    "numpy>=1.24.0" `
    "pillow>=10.0.0" `
    "websockets>=13.0"

if ($LASTEXITCODE -ne 0) {
    throw "pip install that bai voi ma loi $LASTEXITCODE"
}

# Include msvcp140.dll in runtime if present on host (needed by OpenCV on bare Windows VMs)
$Msvcp = Join-Path $env:SystemRoot "System32\msvcp140.dll"
if ((Test-Path $Msvcp) -and -not (Test-Path (Join-Path $RuntimeDir "msvcp140.dll"))) {
    Copy-Item -Path $Msvcp -Destination $RuntimeDir -Force
}

# Remove __pycache__ inside bundled site-packages to keep zip clean
Get-ChildItem -Path $SitePackagesDir -Directory -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# 5. Copy tool code, assets, and user launchers
Write-Host "[4/5] Dang chep code tool, assets va tao file khoi chay..."
Copy-Item -Path (Join-Path $HybridDir "bridge.py") -Destination (Join-Path $AppDir "bridge.py") -Force
Copy-Item -Path (Join-Path $HybridDir "assets\*.rgb") -Destination $AssetsDir -Force

$ChromeBat = @'
@echo off
setlocal
title Chrome Debug 9222 - NomStead

set "BROWSER_BIN="
set "BROWSER_NAME="

if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    set "BROWSER_BIN=C:\Program Files\Google\Chrome\Application\chrome.exe"
    set "BROWSER_NAME=Google Chrome"
)
if not defined BROWSER_BIN if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    set "BROWSER_BIN=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    set "BROWSER_NAME=Google Chrome"
)
if not defined BROWSER_BIN if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
    set "BROWSER_BIN=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
    set "BROWSER_NAME=Google Chrome"
)

:: Fallback sang Microsoft Edge (co san tren moi may Windows 10/11) neu may chua cai Chrome
if not defined BROWSER_BIN if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
    set "BROWSER_BIN=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    set "BROWSER_NAME=Microsoft Edge"
)
if not defined BROWSER_BIN if exist "C:\Program Files\Microsoft\Edge\Application\msedge.exe" (
    set "BROWSER_BIN=C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    set "BROWSER_NAME=Microsoft Edge"
)

if not defined BROWSER_BIN (
    echo [LOI] Khong tim thay Google Chrome hoac Microsoft Edge tren may!
    pause
    exit /b 1
)

echo ========================================================
echo DANG KHOI DONG %BROWSER_NAME% DEBUG CHO NOMSTEAD
echo ========================================================
echo Trinh duyet: "%BROWSER_BIN%"
echo Port       : 9222
echo.

start "" "%BROWSER_BIN%" --remote-debugging-port=9222 --user-data-dir="%~dp0chrome_debug_profile" --disable-background-timer-throttling --disable-backgrounding-occluded-windows --disable-renderer-backgrounding --mute-audio --no-first-run --no-default-browser-check --disable-extensions --disable-sync --disable-translate --disable-component-update --disable-background-networking --disable-default-apps --no-pings --disable-features=Translate,BackForwardCache,MediaRouter,OptimizationHints --js-flags="--max-old-space-size=1024" "https://nomstead.com"

echo [OK] Da mo %BROWSER_NAME% thanh cong!
echo Hay dang nhap game tren cua so vua mo.
echo ========================================================
if /i "%~1" NEQ "--no-pause" pause
'@
Set-Content -Path (Join-Path $PackageDir "Mo_Chrome_Game.bat") -Value $ChromeBat -Encoding Ascii

$RunBat = @'
@echo off
setlocal
title NomStead Auto Fishing - Portable
color 0B

cd /d "%~dp0"

echo ================================================================
echo          NOMSTEAD AUTO FISHING - BAN PORTABLE (KHONG CAN CAI)
echo ================================================================
echo.

if not exist "%~dp0runtime\python.exe" (
    echo [LOI] Thieu thu muc runtime! Hay giai nen day du file .zip truoc khi chay.
    pause
    exit /b 1
)

:: 1. Kiem tra cong Chrome Debug 9222
echo [1/3] Kiem tra trinh duyet game - port 9222...
netstat -ano | findstr :9222 >nul
if errorlevel 1 goto :launch_browser
echo [OK] Trinh duyet game port 9222 da san sang.
goto :ask_lake

:launch_browser
echo [THONG BAO] Chua mo trinh duyet game - Dang tu dong mo...
call "%~dp0Mo_Chrome_Game.bat" --no-pause
timeout /t 3 /nobreak >nul
echo.
echo Hay dang nhap game NomStead tren cua so trinh duyet vua mo roi tiep tuc ben duoi.

:ask_lake
:: 2. Nhap so ho bat dau
echo.
echo [2/3] Cau hinh phien cau ca:
set "START_LAKE="
set /p START_LAKE="Nhap so ho bat dau [1-40] (Nhan Enter de mac dinh ho 1): "
if "%START_LAKE%"=="" set "START_LAKE=1"
set "START_LAKE_NUM=1"
set /a START_LAKE_NUM=%START_LAKE% 2>nul
if %START_LAKE_NUM% lss 1 set "START_LAKE_NUM=1"
if %START_LAKE_NUM% gtr 40 set "START_LAKE_NUM=40"
set "START_LAKE=%START_LAKE_NUM%"

:: 3. Chay Auto Loop bang Python Embeddable di kem
echo.
echo [3/3] Dang khoi dong Vong lap Treo Game...
echo ----------------------------------------------------------------
echo Ho bat dau : Ho %START_LAKE%
echo Che do     : Auto Loop 40 Ho - An banh mi tu dong + Watchdog
echo Huong dan  : Nhan Ctrl+C de DUNG TOOL AN TOAN bat cu luc nao.
echo ----------------------------------------------------------------
echo.

"%~dp0runtime\python.exe" -u "%~dp0app\bridge.py" --auto --lake %START_LAKE% --state-file "%~dp0session_state.json"

echo.
echo ================================================================
echo Phien cau ca da ket thuc an toan.
echo ================================================================
pause
'@
Set-Content -Path (Join-Path $PackageDir "AutoCauCa.bat") -Value $RunBat -Encoding Ascii

$ReadmeTxt = @'
================================================================
           HUONG DAN SU DUNG AUTO CAU CA (PORTABLE)
================================================================

KHONG CAN CAI PYTHON, KHONG CAN GIT, KHONG CAN CAI THEM GI!
Chi can giai nen file .zip ra mot thu muc (vi du: D:\AutoCauCa).

CACH CHAY:
1. Lan dau: bam dup "Mo_Chrome_Game.bat" -> dang nhap game NomStead
   va vao nhan vat. (Trinh duyet se tu luu dang nhap trong thu muc
   chrome_debug_profile nen nhung lan sau khong can dang nhap lai.)
2. Bam dup "AutoCauCa.bat" -> nhap so ho bat dau (1-40) -> Enter.
   (Neu ban quen mo game truoc, AutoCauCa.bat cung tu dong mo giup.)
3. Nhan Ctrl+C trong cua so den de dung tool an toan.

LUU Y:
- Giu nguyen cac thu muc "runtime" va "app" cung cho voi file .bat.
- Neu may chua cai Google Chrome, tool tu dong dung Microsoft Edge
  co san tren Windows.
================================================================
'@
Set-Content -Path (Join-Path $PackageDir "HUONG_DAN.txt") -Value $ReadmeTxt -Encoding UTF8

# 6. Smoke test the bundled runtime before zipping
Write-Host "[5/5] Dang kiem tra runtime va nen file ZIP..."
$PortablePython = Join-Path $RuntimeDir "python.exe"
& $PortablePython -c "import cv2, numpy, PIL, websockets, bridge; assert bridge._load_water_means() is not None; assert bridge._get_alert_template().shape == (35, 33, 3); assert bridge._get_bread_template().shape == (33, 43, 3); print('PORTABLE SMOKE OK: cv2=' + cv2.__version__ + ' numpy=' + numpy.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw "Kiem tra runtime portable that bai!"
}

Compress-Archive -Path $PackageDir -DestinationPath $ZipOut -CompressionLevel Optimal -Force

$ZipSizeMB = [math]::Round((Get-Item $ZipOut).Length / 1MB, 2)
Write-Host ""
Write-Host "========================================================" -ForegroundColor Green
Write-Host "  [OK] DONG GOI THANH CONG!" -ForegroundColor Green
Write-Host "  Thu muc : $PackageDir" -ForegroundColor Green
Write-Host "  File ZIP: $ZipOut ($ZipSizeMB MB)" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
