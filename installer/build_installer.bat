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
set "CACHE=installer\cache"
set "PYVER=3.13.7"
set "EMBED_ZIP=%CACHE%\python-%PYVER%-embed-amd64.zip"
set "EMBED_URL=https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-embed-amd64.zip"
set "GET_PIP=%CACHE%\get-pip.py"
set "GET_PIP_URL=https://bootstrap.pypa.io/get-pip.py"

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

if not exist "%CACHE%" mkdir "%CACHE%"

echo [1/7] Building TierMaps.ico from TierMaps.png...
if not exist "TierMaps.png" (
    echo ERROR: TierMaps.png not found in repository root.
    exit /b 1
)
if not exist "venv\Scripts\python.exe" (
    echo ERROR: Development venv not found. Run install.bat first.
    exit /b 1
)
venv\Scripts\pip.exe install pillow --quiet
if errorlevel 1 exit /b 1
venv\Scripts\python.exe installer\make_icon.py TierMaps.png installer\TierMaps.ico
if errorlevel 1 exit /b 1

echo [2/7] Preparing staging folder...
if exist "%STAGE%" (
    powershell -NoProfile -Command "Remove-Item -LiteralPath '%STAGE%' -Recurse -Force -ErrorAction SilentlyContinue"
)
mkdir "%STAGE%"
mkdir "%STAGE%\data" 2>nul
mkdir "%STAGE%\python\Lib\site-packages" 2>nul

echo [3/7] Copying application files...
robocopy "xpostmaps" "%STAGE%\xpostmaps" /E /NFL /NDL /NJH /NJS /NC /NS /NP ^
    /XD __pycache__ .pytest_cache ^
    /XF *.pyc *.pyo
if %ERRORLEVEL% GEQ 8 exit /b 1

copy /Y "run.py" "%STAGE%\" >nul
copy /Y "requirements.txt" "%STAGE%\" >nul
copy /Y "installer\TierMaps.bat" "%STAGE%\TierMaps.bat" >nul
copy /Y "TierMaps.png" "%STAGE%\TierMaps.png" >nul
copy /Y "installer\TierMaps.ico" "%STAGE%\TierMaps.ico" >nul
echo. > "%STAGE%\data\.gitkeep"

echo [4/7] Downloading Windows embeddable Python %PYVER%...
if not exist "%EMBED_ZIP%" (
    powershell -NoProfile -Command ^
        "Invoke-WebRequest -Uri '%EMBED_URL%' -OutFile '%EMBED_ZIP%'"
    if errorlevel 1 (
        echo ERROR: Failed to download embeddable Python.
        exit /b 1
    )
)

echo [5/7] Extracting portable Python runtime...
powershell -NoProfile -Command ^
    "Expand-Archive -LiteralPath '%EMBED_ZIP%' -DestinationPath '%STAGE%\python' -Force"
if errorlevel 1 exit /b 1

for %%F in ("%STAGE%\python\python*._pth") do (
    >"%%F" (
        echo python313.zip
        echo .
        echo Lib\site-packages
        echo import site
    )
)

if not exist "%GET_PIP%" (
    powershell -NoProfile -Command ^
        "Invoke-WebRequest -Uri '%GET_PIP_URL%' -OutFile '%GET_PIP%'"
    if errorlevel 1 (
        echo ERROR: Failed to download get-pip.py
        exit /b 1
    )
)

echo [6/7] Installing Python dependencies into portable runtime - may take several minutes...
"%STAGE%\python\python.exe" "%GET_PIP%" --no-warn-script-location
if errorlevel 1 exit /b 1

"%STAGE%\python\python.exe" -m pip install --upgrade pip --no-warn-script-location
if errorlevel 1 exit /b 1

set "PYTHONNOUSERSITE=1"
"%STAGE%\python\python.exe" -m pip install -r "%STAGE%\requirements.txt" ^
    --no-warn-script-location --no-user --ignore-installed
if errorlevel 1 (
    echo ERROR: Failed to install Python dependencies into portable runtime.
    exit /b 1
)

echo       Verifying portable runtime...
set "PYTHONNOUSERSITE=1"
"%STAGE%\python\python.exe" -c "import PySide6, pyqtgraph, numpy, numba, pyproj, shapefile, OpenGL; print('OK')"
if errorlevel 1 (
    echo ERROR: Portable runtime verification failed.
    exit /b 1
)

set "QT_QPA_PLATFORM=offscreen"
set "PYTHONNOUSERSITE=1"
"%STAGE%\python\python.exe" -c "import sys; sys.path.insert(0, r'%CD%\%STAGE%'); from xpostmaps.ui.main_window import MainWindow; from PySide6.QtWidgets import QApplication; app=QApplication([]); MainWindow(); print('SMOKE_OK')"
if errorlevel 1 (
    echo ERROR: Application smoke test failed in staging.
    exit /b 1
)

echo [7/7] Compiling NSIS installer...
if not exist "%DIST%" mkdir "%DIST%"
pushd installer
"%NSIS%" /V2 "TierMaps.nsi"
set "RC=%ERRORLEVEL%"
popd
if %RC% neq 0 (
    echo ERROR: NSIS compilation failed.
    exit /b 1
)

echo.
echo Done.
for %%F in ("%DIST%\TierMaps-*-Setup.exe") do (
    echo Installer: %%~fF
    echo Size: %%~zF bytes
)
echo.
echo The installer uses a portable embedded Python runtime and does not require
echo Python to be installed on the target machine.
exit /b 0
