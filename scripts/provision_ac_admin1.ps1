# Create or reset admin1 for Activated Carbon demo (SAM_CARBONS_DEMO + MES_Admin).
#
# Usage (AWS CLI configured, from repo root):
#   .\scripts\provision_ac_admin1.ps1
#   .\scripts\provision_ac_admin1.ps1 -Password 'YourSecurePass1!'
#   .\scripts\provision_ac_admin1.ps1 -EnvFile .env.production

param(
    [string]$Username = "admin1",
    [string]$TenantCode = "SAM_CARBONS_DEMO",
    [string]$Group = "MES_Admin",
    [string]$EnvFile = ".env.production",
    [string]$Password = ""
)

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Provisioner = Join-Path $Root "scripts\provision_cognito_user.ps1"

if ($Password) {
    & $Provisioner -Username $Username -TenantCode $TenantCode -Group $Group -EnvFile $EnvFile -Password $Password
} else {
    & $Provisioner -Username $Username -TenantCode $TenantCode -Group $Group -EnvFile $EnvFile
}

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host @"

Activated Carbon login:
  1. Open https://nyraservices-testbed.net/mes/
  2. Click Activated Carbon Plant
  3. Sign in as username: $Username
  4. Tenant: $TenantCode · Workspace: SAM_CARBONS_DEMO_WS

"@ -ForegroundColor Cyan
