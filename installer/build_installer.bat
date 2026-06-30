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

echo [1/8] Checking required source files...
for %%F in (
    "TierMaps.png"
    "TierMaps_No_bg.png"
    "TierMaps_Logo.png"
    "TierMaps_Logo_grey.png"
    "run.py"
    "preflight.py"
    "requirements.txt"
    "xpostmaps\assets\world_coastlines.json"
    "xpostmaps\assets\world_land_polygons.json"
) do (
    if not exist %%F (
        echo ERROR: Required file missing: %%F
        exit /b 1
    )
)

if not exist "venv\Scripts\python.exe" (
    echo ERROR: Development venv not found. Run install.bat first.
    exit /b 1
)

echo [2/8] Building TierMaps.ico from TierMaps.png...
venv\Scripts\python.exe -m pip install pillow --quiet 2>nul
venv\Scripts\python.exe installer\make_icon.py TierMaps.png installer\TierMaps.ico
if errorlevel 1 exit /b 1

echo [3/8] Syncing development venv with requirements.txt...
venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: Failed to install requirements into development venv.
    exit /b 1
)

echo [4/8] Preparing staging folder...
if exist "%STAGE%" (
    powershell -NoProfile -Command "Remove-Item -LiteralPath '%STAGE%' -Recurse -Force -ErrorAction SilentlyContinue"
)
mkdir "%STAGE%"
mkdir "%STAGE%\data" 2>nul
mkdir "%STAGE%\python\Lib\site-packages" 2>nul

echo [5/8] Copying application files...
robocopy "xpostmaps" "%STAGE%\xpostmaps" /E /NFL /NDL /NJH /NJS /NC /NS /NP ^
    /XD __pycache__ .pytest_cache ^
    /XF *.pyc *.pyo
if %ERRORLEVEL% GEQ 8 exit /b 1

copy /Y "run.py" "%STAGE%\" >nul
copy /Y "preflight.py" "%STAGE%\" >nul
copy /Y "requirements.txt" "%STAGE%\" >nul
copy /Y "installer\TierMaps.bat" "%STAGE%\TierMaps.bat" >nul
copy /Y "TierMaps.png" "%STAGE%\TierMaps.png" >nul
copy /Y "TierMaps_No_bg.png" "%STAGE%\TierMaps_No_bg.png" >nul
copy /Y "TierMaps_Logo.png" "%STAGE%\TierMaps_Logo.png" >nul
copy /Y "TierMaps_Logo_grey.png" "%STAGE%\TierMaps_Logo_grey.png" >nul
copy /Y "installer\TierMaps.ico" "%STAGE%\TierMaps.ico" >nul
copy /Y "installer\default_settings.json" "%STAGE%\data\settings.json" >nul
copy /Y "installer\license.txt" "%STAGE%\license.txt" >nul

echo [6/8] Downloading and extracting portable Python %PYVER%...
if not exist "%EMBED_ZIP%" (
    powershell -NoProfile -Command ^
        "Invoke-WebRequest -Uri '%EMBED_URL%' -OutFile '%EMBED_ZIP%'"
    if errorlevel 1 (
        echo ERROR: Failed to download embeddable Python.
        exit /b 1
    )
)

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

echo [7/8] Bundling Python libraries into install folder...
robocopy "venv\Lib\site-packages" "%STAGE%\python\Lib\site-packages" /E /NFL /NDL /NJH /NJS /NC /NS /NP ^
    /XD __pycache__ .pytest_cache pytest _pytest pluggy iniconfig Pygments ^
    /XF *.pyc *.pyo
if %ERRORLEVEL% GEQ 8 (
    echo ERROR: Failed to copy bundled Python libraries.
    exit /b 1
)

echo       Verifying bundled files...
venv\Scripts\python.exe installer\verify_staging.py "%STAGE%"
if errorlevel 1 exit /b 1

echo       Running application smoke test...
set "APP_ROOT=%CD%\%STAGE%\"
set "PYTHONHOME=%APP_ROOT%python"
set "PYDIR=%PYTHONHOME%\Lib\site-packages"
set "PROJ_DIR=%PYDIR%\pyproj\proj_dir\share\proj"
set "PATH=%PYTHONHOME%;%PYDIR%\PySide6;%PYDIR%\shiboken6;%PYDIR%\llvmlite\binding;%PATH%"
set "QT_PLUGIN_PATH=%PYDIR%\PySide6\plugins"
set "PROJ_LIB=%PROJ_DIR%"
set "PROJ_DATA=%PROJ_DIR%"
set "PYTHONPATH=%APP_ROOT%;%PYDIR%"
set "PYTHONNOUSERSITE=1"
set "QT_QPA_PLATFORM=offscreen"
"%STAGE%\python\python.exe" "%STAGE%\preflight.py"
if errorlevel 1 (
    echo ERROR: Application smoke test failed in staging.
    exit /b 1
)

echo [8/8] Compiling NSIS installer...
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
echo The installer is fully self-contained. No Python or other dependencies
echo are required on the target machine.
exit /b 0
