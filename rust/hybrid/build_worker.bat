@echo off
setlocal
cd /d "%~dp0"
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64
if errorlevel 1 exit /b 1
"%USERPROFILE%\.cargo\bin\rustc.exe" --edition 2021 worker.rs -C opt-level=z -C lto -C codegen-units=1 -C strip=symbols -o worker.exe
if errorlevel 1 exit /b 1
"%USERPROFILE%\.cargo\bin\rustc.exe" --edition 2021 --test tests\worker_tests.rs -C opt-level=z -C lto -C codegen-units=1 -C strip=symbols -o worker_tests.exe
exit /b %errorlevel%
