# Empty client reset for GR Carbons - masters only, no demo inward/lots.
#
# Usage (venv active, MES_CORE_DB_PASSWORD in .env):
#   .\scripts\reset_gr_carbons_client.ps1

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

& "$Root\venv\Scripts\Activate.ps1"

Remove-Item Env:NYRA_USE_DEMO_ENV -ErrorAction SilentlyContinue
$env:DEMO_MODE = "false"
$env:DEMO_READ_ONLY = "false"
$env:DEFAULT_TENANT_CODE = "GR_CARBONS"
$env:AC_TENANT_CODE = "GR_CARBONS"
$env:AC_WORKSPACE_CODE = "GR_CARBONS_ACTIVATED_CARBON"

Write-Host ""
Write-Host "=== Client reset: GR Carbons (masters only, empty plant) ===" -ForegroundColor Cyan

Write-Host "Step 0/4: Ensure tenant codes are GR_CARBONS..." -ForegroundColor Cyan
python scripts/rename_tenant_gr_carbons.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Step 1/4: Ensure PostgreSQL sequences exist..." -ForegroundColor Cyan
python scripts/apply_mes_core_sequences.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Step 2/4: Wipe tenant data, reinstall master, reset sequences..." -ForegroundColor Cyan
python scripts/seed_sam_carbons_demo.py --reset-all --install-master --reset-sequences --masters-only --force
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Step 3/4: Verify business-code sequences..." -ForegroundColor Cyan
python scripts/reset_all_sequences.py

Write-Host ""
Write-Host "Step 4/4 (optional): Apply GR notebook process on coconut shell..." -ForegroundColor Cyan
python scripts/seed_gr_carbons_process_flow.py
if ($LASTEXITCODE -ne 0) { Write-Host "WARN: GR process seed skipped or failed" -ForegroundColor Yellow }

Write-Host ""
Write-Host "Done. Plant is empty - configure via Super Admin in the UI." -ForegroundColor Green
Write-Host "Tenant: GR_CARBONS  Workspace: GR_CARBONS_ACTIVATED_CARBON"
Write-Host "Restart API (run_sam_carbons_api_8003.ps1) and refresh nyra-mes-ui .env.ac."
Write-Host ""
