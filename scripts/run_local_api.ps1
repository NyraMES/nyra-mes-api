# Start Nyra MES API locally for nyra_mes_core testing.
# Usage: .\scripts\run_local_api.ps1

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

& "$Root\venv\Scripts\Activate.ps1"

Write-Host "Checking nyra_mes_core connection..." -ForegroundColor Cyan
python scripts/verify_mes_core_connection.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "Fix .env (MES_CORE_DB_PASSWORD) then re-run." -ForegroundColor Yellow
    exit $LASTEXITCODE
}

Write-Host "`nStarting API at http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "Swagger: http://127.0.0.1:8000/docs" -ForegroundColor Green
Write-Host "Try: GET /api/context, GET /api/products`n" -ForegroundColor Green

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
