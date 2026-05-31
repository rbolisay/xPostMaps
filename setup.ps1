# xPostMaps setup (Windows)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment..."
    python -m venv venv
}

Write-Host "Installing dependencies..."
& ".\venv\Scripts\pip.exe" install -r requirements.txt

Write-Host "Done. Run: .\run.bat"
