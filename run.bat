@echo off
setlocal
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo Virtual environment not found. Running install.bat ...
    call "%~dp0install.bat"
    if errorlevel 1 exit /b 1
)
start "" "venv\Scripts\pythonw.exe" "run.py" %*
exit /b 0
