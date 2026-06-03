@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0venv\Scripts\pythonw.exe" (
    echo TierMaps could not start. The application runtime is missing.
    echo Please reinstall TierMaps from the original setup package.
    pause
    exit /b 1
)

start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0run.py" %*
exit /b 0
