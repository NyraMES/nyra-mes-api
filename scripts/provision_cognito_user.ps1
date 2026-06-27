# Create or reset a tenant-scoped Cognito user for Nyra MES.
# Requires AWS CLI + Cognito user pool with custom attribute: tenant_code
# (appears in JWT as custom:tenant_code).
#
# Usage:
#   .\scripts\provision_cognito_user.ps1 -TenantCode SAM_CARBONS_DEMO -Group MES_Planner
#   .\scripts\provision_cognito_user.ps1 -TenantCode SAM_CARBONS -Email user@client.com
#   .\scripts\provision_cognito_user.ps1 -EnvFile .env.demo -TenantCode NYRA_VIDEO_DEMO

param(
    [string]$Email = "",
    [string]$Password = "",
    [string]$Group = "MES_Planner",
    [Parameter(Mandatory = $true)]
    [string]$TenantCode,
    [string]$EnvFile = ".env.demo"
)

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EnvPath = Join-Path $Root $EnvFile
if (Test-Path $EnvPath) {
    Get-Content $EnvPath | ForEach-Object {
        if ($_ -match '^\s*([^#=]+)=(.*)$') {
            Set-Item -Path "env:$($Matches[1].Trim())" -Value $Matches[2].Trim()
        }
    }
}

$PoolId = $env:COGNITO_USER_POOL_ID
$Region = $env:COGNITO_REGION
if (-not $PoolId -or -not $Region) {
    Write-Host "ERROR: Set COGNITO_USER_POOL_ID and COGNITO_REGION in $EnvFile" -ForegroundColor Red
    exit 1
}

if (-not $Email) {
    switch ($TenantCode) {
        "SAM_CARBONS_DEMO" {
            $role = ($Group -replace "^MES_", "").ToLower()
            $Email = "ac-demo-$role@nyra.local"
        }
        "AUTO_OEM_DEMO" {
            $role = ($Group -replace "^MES_", "").ToLower()
            $Email = "oem-$role@nyra.local"
        }
        "NYRA_VIDEO_DEMO" { $Email = "demo-viewer@nyra-demo.local" }
        default { $Email = "user-$($TenantCode.ToLower())@nyra.local" }
    }
}

if (-not $Password) {
    $Password = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 16 | ForEach-Object { [char]$_ })
    $Password = "Nyra!" + $Password
}

Write-Host "Provisioning Cognito user for tenant $TenantCode" -ForegroundColor Cyan
Write-Host "  Email: $Email" -ForegroundColor Cyan

$userExists = $false
try {
    aws cognito-idp admin-get-user `
        --user-pool-id $PoolId `
        --username $Email `
        --region $Region 2>$null | Out-Null
    $userExists = $true
    Write-Host "User already exists - updating tenant and password." -ForegroundColor Yellow
} catch {
    $userExists = $false
}

if (-not $userExists) {
    aws cognito-idp admin-create-user `
        --user-pool-id $PoolId `
        --username $Email `
        --user-attributes `
            Name=email,Value=$Email `
            Name=email_verified,Value=true `
            Name=custom:tenant_code,Value=$TenantCode `
        --message-action SUPPRESS `
        --region $Region
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    aws cognito-idp admin-update-user-attributes `
        --user-pool-id $PoolId `
        --username $Email `
        --user-attributes Name=custom:tenant_code,Value=$TenantCode `
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

aws cognito-idp get-group --group-name $Group --user-pool-id $PoolId --region $Region 2>$null
if ($LASTEXITCODE -ne 0) {
    aws cognito-idp create-group `
        --group-name $Group `
        --user-pool-id $PoolId `
        --description "Nyra MES role $Group" `
        --region $Region
}

aws cognito-idp admin-add-user-to-group `
    --user-pool-id $PoolId `
    --username $Email `
    --group-name $Group `
    --region $Region

Write-Host @"

OK: Tenant-scoped Cognito user ready.

  Email       : $Email
  Password    : $Password
  Group       : $Group
  Tenant code : $TenantCode  (custom:tenant_code)

Cognito pool must define custom attribute tenant_code (mutable).
Users can only access API routes for their assigned tenant when AUTH_ENABLED=true.

"@ -ForegroundColor Green
