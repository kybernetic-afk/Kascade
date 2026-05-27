@echo off
title Build Kascade
cd /d "%~dp0"

echo Installing build dependencies...
python -m pip install -r requirements.txt pyinstaller

echo.
echo Building single-file Windows app...
pyinstaller --noconfirm --onefile --windowed --name Kascade run_app.py

echo.
echo ==========================================
echo   Build complete.
echo   Executable: dist\Kascade.exe
echo ==========================================
echo.
echo Reminder: keep these next to the .exe (or on PATH):
echo   - bin\bws.exe        (Bitwarden Secrets Manager CLI)
echo   - post_update\       (your post-update files)
echo And set BWS_ACCESS_TOKEN once with:  setx BWS_ACCESS_TOKEN "your-token"
pause
