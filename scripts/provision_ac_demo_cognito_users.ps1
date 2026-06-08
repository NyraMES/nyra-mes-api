# Create one Activated Carbon demo user per MES group (same pattern as Auto OEM).
# All users get custom:tenant_code=SAM_CARBONS_DEMO for testbed / AC demo tenant.
#
# Prerequisites: AWS CLI configured, tenant_code custom attribute on the user pool.
#
# Usage:
#   .\scripts\provision_ac_demo_cognito_users.ps1
#   .\scripts\provision_ac_demo_cognito_users.ps1 -EnvFile .env.production
#   .\scripts\provision_ac_demo_cognito_users.ps1 -TenantCode SAM_CARBONS -EmailPrefix samcarbons

param(
    [string]$TenantCode = "SAM_CARBONS_DEMO",
    [string]$EmailPrefix = "ac-demo",
    [string]$EmailDomain = "nyra.local",
    [string]$EnvFile = ".env.production",
    [string]$SharedPassword = ""
)

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Provisioner = Join-Path $Root "scripts\provision_cognito_user.ps1"

$Groups = @(
    "MES_Admin",
    "MES_Planner",
    "MES_Operator",
    "MES_Quality",
    "MES_Viewer"
)

function GroupSlug($Group) {
    return ($Group -replace "^MES_", "").ToLower()
}

Write-Host "`nProvisioning Activated Carbon users (tenant: $TenantCode) — one per group`n" -ForegroundColor Cyan

$results = @()

foreach ($Group in $Groups) {
    $slug = GroupSlug $Group
    $email = "$EmailPrefix-$slug@$EmailDomain"
    Write-Host "--- $Group -> $email ---" -ForegroundColor Yellow

    $args = @(
        "-TenantCode", $TenantCode,
        "-Group", $Group,
        "-Email", $email,
        "-EnvFile", $EnvFile
    )
    if ($SharedPassword) {
        $args += @("-Password", $SharedPassword)
    }

    & $Provisioner @args
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $email ($Group)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
    $results += [PSCustomObject]@{ Group = $Group; Email = $email }
}

Write-Host "`nAll Activated Carbon demo users provisioned.`n" -ForegroundColor Green
Write-Host "Tenant code on every user: $TenantCode (custom:tenant_code)`n"
Write-Host ("{0,-14} {1}" -f "Group", "Email")
Write-Host ("{0,-14} {1}" -f "-----", "-----")
foreach ($row in $results) {
    Write-Host ("{0,-14} {1}" -f $row.Group, $row.Email)
}
Write-Host "`nPasswords were printed above for each user (or use your -SharedPassword).`n"
Write-Host "Testbed login: https://nyraservices-testbed.net/mes/ -> Activated Carbon -> sign in.`n"
