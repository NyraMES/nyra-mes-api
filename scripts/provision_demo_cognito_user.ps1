# Create a disposable Cognito user for the NYRA_VIDEO_DEMO tenant.
# Prefer provision_cognito_user.ps1 for new tenant-scoped users (custom:tenant_code).
#
# Usage:
#   .\scripts\provision_demo_cognito_user.ps1
#   .\scripts\provision_cognito_user.ps1 -TenantCode SAM_CARBONS_DEMO -Group MES_Planner

param(
    [string]$Email = "demo-viewer@nyra-demo.local",
    [string]$Password = "",
    [string]$Group = "MES_Planner"
)

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$DemoEnv = Join-Path $Root ".env.demo"
if (Test-Path $DemoEnv) {
    Get-Content $DemoEnv | ForEach-Object {
        if ($_ -match '^\s*([^#=]+)=(.*)$') {
            Set-Item -Path "env:$($Matches[1].Trim())" -Value $Matches[2].Trim()
        }
    }
}

$PoolId = $env:COGNITO_USER_POOL_ID
$Region = $env:COGNITO_REGION
if (-not $PoolId -or -not $Region) {
    Write-Host "ERROR: Set COGNITO_USER_POOL_ID and COGNITO_REGION in .env.demo" -ForegroundColor Red
    exit 1
}

if (-not $Password) {
    # Cognito-safe temp password (user must change on first login unless Permanent)
    $Password = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 16 | ForEach-Object { [char]$_ })
    $Password = "Nyra!" + $Password
}

Write-Host "Creating Cognito user: $Email" -ForegroundColor Cyan

$userExists = $false
try {
    aws cognito-idp admin-get-user `
        --user-pool-id $PoolId `
        --username $Email `
        --region $Region 2>$null | Out-Null
    $userExists = $true
    Write-Host "User already exists — resetting password only." -ForegroundColor Yellow
} catch {
    $userExists = $false
}

if (-not $userExists) {
    aws cognito-idp admin-create-user `
        --user-pool-id $PoolId `
        --username $Email `
        --user-attributes Name=email,Value=$Email Name=email_verified,Value=true `
        --message-action SUPPRESS `
        --region $Region
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

aws cognito-idp admin-set-user-password `
    --user-pool-id $PoolId `
    --username $Email `
    --password $Password `
    --permanent `
    --region $Region
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Ensure group exists and add user
aws cognito-idp get-group --group-name $Group --user-pool-id $PoolId --region $Region 2>$null
if ($LASTEXITCODE -ne 0) {
    aws cognito-idp create-group `
        --group-name $Group `
        --user-pool-id $PoolId `
        --description "Nyra MES demo planner role" `
        --region $Region
}

aws cognito-idp admin-add-user-to-group `
    --user-pool-id $PoolId `
    --username $Email `
    --group-name $Group `
    --region $Region

Write-Host @"

OK: Demo Cognito user ready.

  Email    : $Email
  Password : $Password
  Group    : $Group
  Tenant   : NYRA_VIDEO_DEMO

Give these credentials ONLY to video tools / prospects under NDA.
Rotate password after recording: re-run this script.

Set in .env.demo for hosted API:
  AUTH_ENABLED=true

"@ -ForegroundColor Green
