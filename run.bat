@echo off
setlocal
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv venv
    call venv\Scripts\pip install -r requirements.txt
)
call venv\Scripts\python.exe run.py %*
