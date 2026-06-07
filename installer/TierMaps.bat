@echo off
setlocal
cd /d "%~dp0"

set "APP_ROOT=%~dp0"
set "PYTHONHOME=%APP_ROOT%python"
set "PYDIR=%PYTHONHOME%\Lib\site-packages"
set "PATH=%PYTHONHOME%;%PYDIR%\PySide6;%PATH%"
set "QT_PLUGIN_PATH=%PYDIR%\PySide6\plugins"
set "PYTHONPATH=%APP_ROOT%;%PYDIR%"
set "PYTHONNOUSERSITE=1"

if not exist "%PYTHONHOME%\pythonw.exe" (
    echo TierMaps could not start. The bundled Python runtime is missing.
    echo Please reinstall TierMaps from the original setup package.
    pause
    exit /b 1
)

start "" "%PYTHONHOME%\pythonw.exe" "%APP_ROOT%run.py" %*
exit /b 0
