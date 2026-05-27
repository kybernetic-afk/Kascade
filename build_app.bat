@echo off
title Build Kascade
cd /d "%~dp0"

echo Installing build dependencies...
python -m pip install -r requirements.txt pyinstaller

echo.
echo Generating version info...
python scripts\make_version_file.py

echo.
echo Building single-file Windows app...
python -m PyInstaller --noconfirm --onefile --windowed --name Kascade ^
  --icon assets\icon.ico ^
  --add-data "assets\icon.ico;assets" ^
  --version-file version_info.txt ^
  run_app.py
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)

echo.
echo Building installer...
rem Read the app version for the installer filename / metadata.
for /f "delims=" %%v in ('python -c "import kascade; print(kascade.__version__)"') do set "APPVER=%%v"

rem Locate the Inno Setup compiler: PATH first, then the common install folders
rem (machine-wide Program Files, or a per-user winget install under LocalAppData).
set "ISCC="
for /f "delims=" %%p in ('where ISCC.exe 2^>nul') do set "ISCC=%%p"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC goto :no_iscc

"%ISCC%" /DAppVersion=%APPVER% installer.iss
if errorlevel 1 goto :no_iscc

echo.
echo ==========================================
echo   Build complete.
echo   Portable exe: dist\Kascade.exe
echo   Installer:    dist\Kascade-Setup.exe
echo ==========================================
echo.
echo The app downloads the Bitwarden CLI and creates its own folders on first run.
pause
exit /b 0

:no_iscc
echo.
echo ==========================================
echo   Portable exe built: dist\Kascade.exe
echo   Installer SKIPPED - Inno Setup was not found.
echo   Install it from https://jrsoftware.org/isdl.php
echo   (or: winget install JRSoftware.InnoSetup), then re-run.
echo ==========================================
echo.
pause
exit /b 0
