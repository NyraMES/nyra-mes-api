# Empty client reset for SAM_CARBONS — masters only, no demo inward/lots.
#
# Use when onboarding a real customer: plant resources, products, routing templates
# exist, but the dashboard starts at zero until the first inward receipt.
#
# Usage (venv active, DB credentials in .env):
#   .\scripts\reset_sam_carbons_client.ps1

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

& "$Root\venv\Scripts\Activate.ps1"

Remove-Item Env:NYRA_USE_DEMO_ENV -ErrorAction SilentlyContinue
$env:DEMO_MODE = "false"
$env:DEMO_READ_ONLY = "false"
$env:DEFAULT_TENANT_CODE = "SAM_CARBONS"
$env:AC_TENANT_CODE = "SAM_CARBONS"
$env:AC_WORKSPACE_CODE = "SAM_CARBONS_ACTIVATED_CARBON"

Write-Host "`n=== Client reset: SAM_CARBONS (masters only, empty plant) ===" -ForegroundColor Cyan

Write-Host "Step 1/2: Ensure PostgreSQL sequences exist..." -ForegroundColor Cyan
python scripts/apply_mes_core_sequences.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Step 2/2: Wipe tenant data, reinstall master, reset sequences (no seed story)..." -ForegroundColor Cyan
python scripts/seed_sam_carbons_demo.py --reset-all --install-master --reset-sequences --masters-only --force
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`nDone. Dashboard stock will be zero until you run the production flow." -ForegroundColor Green
Write-Host "Masters: RAW-COCO-SHELL, AC-GRAN-8x30, RT-AC-8x30-V1, RES-KILN-01, CUST-AC-001"
Write-Host "Flow: Raw Material inward -> Prep -> QC -> Release -> Feasibility -> Execution`n"
