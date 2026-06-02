# xPostMaps — install all dependencies locally (for development and future installer)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python is not on PATH. Install Python 3.10+ and try again."
}

if (-not (Test-Path "venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment in .\venv ..."
    python -m venv venv
}

Write-Host "Upgrading pip..."
& ".\venv\Scripts\python.exe" -m pip install --upgrade pip

Write-Host "Installing packages from requirements.txt..."
& ".\venv\Scripts\pip.exe" install -r requirements.txt

Write-Host "Writing requirements-lock.txt..."
& ".\venv\Scripts\pip.exe" freeze | Out-File -Encoding utf8 "requirements-lock.txt"

Write-Host ""
Write-Host "Done. All libraries are installed in .\venv"
Write-Host "Run the app with: .\run.bat"
