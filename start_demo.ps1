<#
.SYNOPSIS
    Start ThermalGuard demo stack: backend API + dashboard + public app.
    Each service runs in its own persistent PowerShell window.

.DESCRIPTION
    Launches three separate PowerShell windows:
    1. Backend (uvicorn on port 8000)
    2. Dashboard (Vite on port 5173)
    3. Public App (Vite on port 5174)

    Windows remain open after script exits so services keep running.
    Use the window close buttons or Ctrl+C in each window to stop.

.PREREQUISITES
    - .venv exists with backend dependencies (run once: python -m venv .venv; .venv\Scripts\pip install -r backend\requirements.txt)
    - dashboard/node_modules exists (run once: cd dashboard; npm install)
    - public-app/node_modules exists (run once: cd public-app; npm install)
    - data/firms_seed.csv and data/osm_seed.geojson exist (run once: python scripts\generate_seed_data.py)
#>

$ErrorActionPreference = "Stop"

Write-Host "== ThermalGuard Demo Stack =="
Write-Host "Starting all services in separate windows..."
Write-Host ""

# 0. Ensure seed data exists
if (-not (Test-Path "data\firms_seed.csv")) {
    Write-Host "Generating seed data..."
    python scripts\generate_seed_data.py
}

# 1. Backend
Write-Host "Launching backend (port 8000)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "cd `"$PSScriptRoot`"; .venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000" `
    -WindowStyle Normal -WorkingDirectory $PSScriptRoot

# 2. Dashboard
Write-Host "Launching dashboard (port 5173)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "cd `"$PSScriptRoot\dashboard`"; npx vite --port 5173 --host 127.0.0.1" `
    -WindowStyle Normal -WorkingDirectory "$PSScriptRoot\dashboard"

# 3. Public App
Write-Host "Launching public app (port 5174)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "cd `"$PSScriptRoot\public-app`"; npx vite --port 5174 --host 127.0.0.1" `
    -WindowStyle Normal -WorkingDirectory "$PSScriptRoot\public-app"

Write-Host ""
Write-Host "== Services Started =="
Write-Host "Backend API : http://127.0.0.1:8000 (docs: /docs)"
Write-Host "Dashboard   : http://127.0.0.1:5173"
Write-Host "Public App  : http://127.0.0.1:5174"
Write-Host ""
Write-Host "Each service runs in its own PowerShell window."
Write-Host "Close the windows or press Ctrl+C in each to stop."