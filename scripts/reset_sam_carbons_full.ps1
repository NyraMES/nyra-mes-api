# Full reset for SAM_CARBONS Activated Carbon:
#   - Wipe all tenant transactional + master rows
#   - Re-apply master SQL (products, routing, RES-KILN-01, CUST-AC-001, …)
#   - Reset PostgreSQL business-code sequences
#   - Seed demo lots with auto-generated ORD-AC-*, PO-AC-*, LOT-AC-*, …
#
# Usage (venv active, valid MES_CORE_DB_PASSWORD in .env):
#   .\scripts\reset_sam_carbons_full.ps1

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

& "$Root\venv\Scripts\Activate.ps1"

Remove-Item Env:NYRA_USE_DEMO_ENV -ErrorAction SilentlyContinue
$env:DEMO_MODE = "false"
$env:DEMO_READ_ONLY = "false"
$env:DEFAULT_TENANT_CODE = "SAM_CARBONS"
$env:AC_TENANT_CODE = "SAM_CARBONS"
$env:AC_WORKSPACE_CODE = "SAM_CARBONS_ACTIVATED_CARBON"

Write-Host "`n=== Full reset: SAM_CARBONS Activated Carbon ===" -ForegroundColor Cyan

Write-Host "Step 1/3: Ensure PostgreSQL sequences exist..." -ForegroundColor Cyan
python scripts/apply_mes_core_sequences.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Step 2/3: Wipe tenant data, reinstall master, reset sequences..." -ForegroundColor Cyan
python scripts/seed_sam_carbons_demo.py --reset-all --install-master --reset-sequences --force
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`nDone. Transactional codes were auto-generated (ORD-AC-*, PO-AC-*, LOT-AC-*)." -ForegroundColor Green
Write-Host "Master SKUs unchanged: RAW-COCO-SHELL, AC-GRAN-8x30, RES-KILN-01, CUST-AC-001"
Write-Host "Restart the API if running, then refresh the UI.`n"
