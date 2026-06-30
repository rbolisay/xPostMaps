@echo off
setlocal
cd /d "%~dp0"

set "APP_ROOT=%~dp0"
set "PYTHONHOME=%APP_ROOT%python"
set "PYDIR=%PYTHONHOME%\Lib\site-packages"
set "PROJ_DIR=%PYDIR%\pyproj\proj_dir\share\proj"

rem All bundled native libraries must resolve from the install folder only.
set "PATH=%PYTHONHOME%;%PYDIR%\PySide6;%PYDIR%\shiboken6;%PYDIR%\llvmlite\binding;%PATH%"
set "QT_PLUGIN_PATH=%PYDIR%\PySide6\plugins"
set "PROJ_LIB=%PROJ_DIR%"
set "PROJ_DATA=%PROJ_DIR%"
set "PYTHONPATH=%APP_ROOT%;%PYDIR%"
set "PYTHONNOUSERSITE=1"

if not exist "%PYTHONHOME%\pythonw.exe" (
    echo TierMaps could not start. The bundled Python runtime is missing.
    echo Expected: %PYTHONHOME%\pythonw.exe
    echo Please reinstall TierMaps from the original setup package.
    pause
    exit /b 1
)

if not exist "%APP_ROOT%data" mkdir "%APP_ROOT%data"

rem Preflight with python.exe so import errors are captured before launching GUI.
"%PYTHONHOME%\python.exe" "%APP_ROOT%preflight.py" >"%APP_ROOT%data\startup.log" 2>&1
if errorlevel 1 (
    echo TierMaps could not start. See data\startup.log for details.
    type "%APP_ROOT%data\startup.log"
    pause
    exit /b 1
)

start "" "%PYTHONHOME%\pythonw.exe" "%APP_ROOT%run.py" %*
exit /b 0
