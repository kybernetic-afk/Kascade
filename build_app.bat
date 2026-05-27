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
pyinstaller --noconfirm --onefile --windowed --name Kascade ^
  --icon assets\icon.ico ^
  --add-data "assets\icon.ico;assets" ^
  --version-file version_info.txt ^
  run_app.py

echo.
echo ==========================================
echo   Build complete.
echo   Executable: dist\Kascade.exe
echo ==========================================
echo.
echo The app downloads the Bitwarden CLI and creates its own folders on first run.
pause
