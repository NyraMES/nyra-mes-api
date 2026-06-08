# Nyra Video Demo — install tenant, seed data, start API
# Usage:
#   copy .env.demo.example .env.demo
#   # Edit .env.demo — add MES_CORE_DB_PASSWORD (same RDS as dev)
#   .\scripts\run_video_demo.ps1

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$DemoEnv = Join-Path $Root ".env.demo"
if (-not (Test-Path $DemoEnv)) {
    Write-Host "Missing .env.demo — copy from .env.demo.example first:" -ForegroundColor Yellow
    Write-Host "  copy .env.demo.example .env.demo" -ForegroundColor Cyan
    exit 1
}

# Load demo env for this session (dotenv in Python also reads .env.demo)
$env:NYRA_USE_DEMO_ENV = "true"
Get-Content $DemoEnv | ForEach-Object {
    if ($_ -match '^\s*([^#=]+)=(.*)$') {
        $name = $Matches[1].Trim()
        $value = $Matches[2].Trim()
        Set-Item -Path "env:$name" -Value $value
    }
}

& "$Root\venv\Scripts\Activate.ps1"

Write-Host "`n=== Nyra Video Demo Environment ===" -ForegroundColor Green
Write-Host "Tenant: NYRA_VIDEO_DEMO (fictional data only)`n" -ForegroundColor Green

Write-Host "Step 1/3: Install demo tenant + master data (idempotent)..." -ForegroundColor Cyan
python scripts/seed_video_demo.py --install-tenant
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`nStep 2/3: Seed workflow data (reset + re-seed)..." -ForegroundColor Cyan
python scripts/seed_video_demo.py --reset
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`nStep 3/3: Starting API..." -ForegroundColor Cyan
Write-Host @"

Demo access (local — no password):
  Email / user : demo-viewer@nyra-demo.local
  Tenant       : NYRA_VIDEO_DEMO  (header X-Tenant-Code)
  API          : http://127.0.0.1:8000/api/context
  Lots         : LOT-DEMO-001 (blocked), LOT-DEMO-002 (complete)
  Ask Nyra     : POST /api/ask  { `"question`": `"Why is LOT-DEMO-001 blocked?`" }

Protection enabled:
  DEMO_MODE=true       — Swagger/docs hidden, ontology & KG API blocked
  DEMO_READ_ONLY=true  — no writes except Ask Nyra (prospect-safe)

Start UI (separate terminal):
  cd d:\Sudha\Nyra\nyra-mes-ui
  copy .env.demo.example .env.demo
  npm run dev:demo
  Open http://localhost:5173/workflow

For hosted demo + Cognito login:
  .\scripts\provision_demo_cognito_user.ps1

"@ -ForegroundColor Green

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
