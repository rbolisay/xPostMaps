@echo off
setlocal
cd /d "%~dp0"

echo xPostMaps - installing dependencies into project folder...
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not on PATH. Install Python 3.10+ and try again.
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment in .\venv ...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        exit /b 1
    )
)

echo Upgrading pip...
call venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 exit /b 1

echo Installing packages from requirements.txt...
call venv\Scripts\pip.exe install -r requirements.txt
if errorlevel 1 exit /b 1

echo Writing requirements-lock.txt...
call venv\Scripts\pip.exe freeze > requirements-lock.txt

echo.
echo Done. All libraries are installed in .\venv
echo Run the app with: run.bat
exit /b 0
