# Start the full ThermalGuard stack locally (no cloud, no docker needed).
# Usage:  .\start_dev.ps1

$ErrorActionPreference = "Stop"

Write-Host "== ThermalGuard local dev =="

# 0. Ensure seed data exists
if (-not (Test-Path "data\firms_seed.csv")) {
    Write-Host "Generating seed data..."
    python scripts\generate_seed_data.py
}

# 1. Backend deps
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
}

# 2. Launch backend (uvicorn)
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m", "uvicorn", `
    "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload" `
    -WorkingDirectory "backend" -WindowStyle Hidden

$deadline = (Get-Date).AddSeconds(30)
do {
    Start-Sleep -Milliseconds 500
    try { $h = Invoke-RestMethod "http://127.0.0.1:8000/api/health"; break } catch {}
} while ((Get-Date) -lt $deadline)
if (-not $h) { Write-Error "Backend failed to start."; exit 1 }
Write-Host "Backend  : http://localhost:8000  (health: $($h.status))"

# 3. Dashboard (5173)
Push-Location dashboard
if (-not (Test-Path node_modules)) { npm install --silent }
Start-Process -FilePath "npm" -ArgumentList "run", "dev" -WorkingDirectory (Get-Location).Path -WindowStyle Hidden
Pop-Location

# 4. Public app (5174)
Push-Location public-app
if (-not (Test-Path node_modules)) { npm install --silent }
Start-Process -FilePath "npm" -ArgumentList "run", "dev" -WorkingDirectory (Get-Location).Path -WindowStyle Hidden
Pop-Location

Write-Host "Dashboard : http://localhost:5173"
Write-Host "Public    : http://localhost:5174"
Write-Host "API docs  : http://localhost:8000/docs"