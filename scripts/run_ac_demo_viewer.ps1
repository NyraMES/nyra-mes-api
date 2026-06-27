# SAM_CARBONS API - prospect demo viewer (MES_Demo: Dashboard + Feasibility only)
#
# Usage:
#   .\scripts\run_ac_demo_viewer.ps1
#
# UI: start nyra-mes-ui separately (e.g. run_local_full_stack.ps1 or npm run dev)
# Open: http://127.0.0.1:5173/activated-carbon/dashboard
#
# Demo viewer sees all sidebar items; only Dashboard and Feasibility Gate are clickable.
# Feasibility is view-only (no Re-run Check / Proceed to Execution). Ask Nyra is hidden.

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

& "$Root\venv\Scripts\Activate.ps1"

Remove-Item Env:NYRA_USE_DEMO_ENV -ErrorAction SilentlyContinue
$env:DEMO_MODE = "false"
$env:DEMO_READ_ONLY = "false"
$env:AUTH_ENABLED = "false"
$env:AUTH_DEV_USER_EMAIL = "ac-demo-demo@nyra.local"
$env:AUTH_DEV_USER_ROLES = "MES_Demo"
$env:AUTH_DEV_USER_TENANT_CODE = "SAM_CARBONS_DEMO"
$env:DEFAULT_TENANT_CODE = "SAM_CARBONS_DEMO"
$env:AC_TENANT_CODE = "SAM_CARBONS_DEMO"
$env:AC_WORKSPACE_CODE = "SAM_CARBONS_DEMO_WS"

Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object {
        if ($_ -and $_ -ne 0) {
            taskkill /F /PID $_ /T 2>$null | Out-Null
            Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
        }
    }
Start-Sleep -Seconds 2

Write-Host ""
Write-Host "=== AC Demo Viewer (MES_Demo) ===" -ForegroundColor Green
Write-Host "Role: MES_Demo - Dashboard + Feasibility Gate only" -ForegroundColor Cyan
Write-Host "API:  http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host "UI:   http://127.0.0.1:5173/activated-carbon/dashboard" -ForegroundColor Cyan
Write-Host ""

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
