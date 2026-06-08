# SAM_CARBONS API — local Activated Carbon validation (read/write, no video demo)
#
# Usage:
#   .\scripts\run_sam_carbons_api.ps1           # start API only
#   .\scripts\run_sam_carbons_api.ps1 -Seed     # reset + seed, then start API
#
# Requires: venv, .env with MES_CORE_DB_PASSWORD

param(
    [switch]$Seed
)

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

& "$Root\venv\Scripts\Activate.ps1"

Remove-Item Env:NYRA_USE_DEMO_ENV -ErrorAction SilentlyContinue
$env:DEMO_MODE = "false"
$env:DEMO_READ_ONLY = "false"
$env:AUTH_ENABLED = "false"
$env:DEFAULT_TENANT_CODE = "SAM_CARBONS"
$env:AC_TENANT_CODE = "SAM_CARBONS"
$env:AC_WORKSPACE_CODE = "SAM_CARBONS_ACTIVATED_CARBON"

Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object {
        if ($_ -and $_ -ne 0) {
            taskkill /F /PID $_ /T 2>$null | Out-Null
            Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
        }
    }
Start-Sleep -Seconds 2

Write-Host "`n=== SAM_CARBONS API ===" -ForegroundColor Green

if ($Seed) {
    Write-Host "Seeding master + demo data..." -ForegroundColor Cyan
    python scripts/apply_mes_core_sequences.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python scripts/seed_sam_carbons_demo.py --install-master --reset --force
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "API:  http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host "Docs: http://127.0.0.1:8000/docs`n" -ForegroundColor Cyan

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
