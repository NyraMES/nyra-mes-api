# GR Carbons (Activated Carbon) API on port 8003 — fallback when 8002 has a stuck listener.
# Update nyra-mes-ui .env.ac: VITE_API_BASE_URL=http://127.0.0.1:8003
#
# Usage:
#   .\scripts\run_sam_carbons_api_8003.ps1

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

& "$Root\venv\Scripts\Activate.ps1"

Remove-Item Env:NYRA_USE_DEMO_ENV -ErrorAction SilentlyContinue
$env:DEMO_MODE = "false"
$env:DEMO_READ_ONLY = "false"
$env:AUTH_ENABLED = "false"
$env:AUTH_DEV_USER_USERNAME = "nyraservices@grcarbons"
$env:AUTH_DEV_USER_ROLES = "MES_Admin"
$env:DEFAULT_TENANT_CODE = "GR_CARBONS"
$env:AC_TENANT_CODE = "GR_CARBONS"
$env:AC_WORKSPACE_CODE = "GR_CARBONS_ACTIVATED_CARBON"

Get-NetTCPConnection -LocalPort 8003 -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object {
        $procId = $_
        if ($procId -and $procId -ne 0) {
            Write-Host "Stopping PID $procId on port 8003..." -ForegroundColor Yellow
            taskkill /F /PID $procId /T 2>$null | Out-Null
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
Start-Sleep -Seconds 2

Write-Host "`n=== GR Carbons API (port 8003) ===" -ForegroundColor Green
Write-Host "API:  http://127.0.0.1:8003" -ForegroundColor Cyan
Write-Host "Docs: http://127.0.0.1:8003/docs`n" -ForegroundColor Cyan

uvicorn app.main:app --host 127.0.0.1 --port 8003
