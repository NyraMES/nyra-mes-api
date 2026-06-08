# Reset Activated Carbon demo transactional data and re-seed with auto-generated codes.
# Master data (products, routing, RES-KILN-01, CUST-AC-001) is preserved.
# For a full wipe including masters, use .\scripts\reset_sam_carbons_full.ps1
#
# Usage (venv active, .env with MES_CORE_DB_PASSWORD):
#   .\scripts\reset_sam_carbons_demo.ps1

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

& "$Root\venv\Scripts\Activate.ps1"

Remove-Item Env:NYRA_USE_DEMO_ENV -ErrorAction SilentlyContinue
$env:DEMO_MODE = "false"
$env:DEMO_READ_ONLY = "false"
$env:DEFAULT_TENANT_CODE = "SAM_CARBONS"
$env:AC_TENANT_CODE = "SAM_CARBONS"
$env:AC_WORKSPACE_CODE = "SAM_CARBONS_ACTIVATED_CARBON"

Write-Host "`n=== Reset Activated Carbon demo data ===" -ForegroundColor Cyan

Write-Host "Step 1/2: Ensure PostgreSQL sequences exist..." -ForegroundColor Cyan
python scripts/apply_mes_core_sequences.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Step 2/2: Wipe transactional data, sync sequences, re-seed..." -ForegroundColor Cyan
python scripts/seed_sam_carbons_demo.py --reset --force --reset-sequences
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`nDone. Check seed output for ORD-AC-*, PO-AC-*, LOT-AC-* codes." -ForegroundColor Green
Write-Host "Restart the API if it is already running, then refresh the UI.`n"
