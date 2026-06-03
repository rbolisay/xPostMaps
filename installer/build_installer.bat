@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."

set "NSIS=C:\Program Files (x86)\NSIS\makensis.exe"
if not exist "%NSIS%" set "NSIS=C:\Program Files\NSIS\makensis.exe"
if not exist "%NSIS%" (
    echo ERROR: NSIS makensis.exe not found. Install NSIS and try again.
    exit /b 1
)

set "STAGE=installer\staging"
set "DIST=dist"

echo.
echo ========================================
echo  TierMaps Installer Build
echo ========================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not on PATH. Install Python 3.10+ 64-bit and try again.
    exit /b 1
)

echo [1/5] Preparing staging folder...
if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%"
mkdir "%STAGE%\data" 2>nul

echo [2/5] Copying application files...
robocopy "xpostmaps" "%STAGE%\xpostmaps" /E /NFL /NDL /NJH /NJS /NC /NS /NP ^
    /XD __pycache__ .pytest_cache ^
    /XF *.pyc *.pyo
if %ERRORLEVEL% GEQ 8 exit /b 1

copy /Y "run.py" "%STAGE%\" >nul
copy /Y "requirements.txt" "%STAGE%\" >nul
copy /Y "installer\TierMaps.bat" "%STAGE%\TierMaps.bat" >nul

echo. > "%STAGE%\data\.gitkeep"

echo [3/5] Building embedded Python environment...
if exist "venv\Scripts\python.exe" (
    echo       Reusing existing .\venv from development tree...
    robocopy "venv" "%STAGE%\venv" /E /NFL /NDL /NJH /NJS /NC /NS /NP ^
        /XD __pycache__ /XF *.pyc *.pyo
    if %ERRORLEVEL% GEQ 8 (
        echo ERROR: Failed to copy virtual environment into staging.
        exit /b 1
    )
) else (
    echo       Creating new venv and installing dependencies - may take several minutes...
    python -m venv "%STAGE%\venv"
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment in staging.
        exit /b 1
    )
    "%STAGE%\venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 exit /b 1
    "%STAGE%\venv\Scripts\pip.exe" install -r "%STAGE%\requirements.txt"
    if errorlevel 1 (
        echo ERROR: Failed to install Python dependencies.
        exit /b 1
    )
)

echo [4/5] Compiling NSIS installer...
if not exist "%DIST%" mkdir "%DIST%"
pushd installer
"%NSIS%" /V2 "TierMaps.nsi"
set "RC=%ERRORLEVEL%"
popd
if %RC% neq 0 (
    echo ERROR: NSIS compilation failed.
    exit /b 1
)

echo [5/5] Done.
echo.
for %%F in ("%DIST%\TierMaps-*-Setup.exe") do (
    echo Installer: %%~fF
    echo Size: %%~zF bytes
)
echo.
echo You can distribute the Setup.exe to end users. They do not need Python installed.
exit /b 0
