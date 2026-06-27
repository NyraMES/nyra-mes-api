# Point testbed nyra-mes-api at RDS Secrets Manager (no stale password in .env).
#
# Usage:
#   .\scripts\deploy\configure_testbed_db.ps1
#   .\scripts\deploy\configure_testbed_db.ps1 -SecretId "rds!db-xxxx"
#
# Requires: deploy-config.ps1, SSH access to testbed EC2.
# EC2 IAM role needs secretsmanager:GetSecretValue (see scripts/iam/ec2-mes-core-secret-read.json).

param(
    [string]$SecretId = ""
)

$ErrorActionPreference = "Stop"
$DeployDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ApiRoot = Split-Path -Parent (Split-Path -Parent $DeployDir)
$ConfigPath = Join-Path $DeployDir "deploy-config.ps1"

if (-not (Test-Path $ConfigPath)) {
    Write-Host "ERROR: Create $ConfigPath from deploy-config.ps1.example" -ForegroundColor Red
    exit 1
}
. $ConfigPath

if (-not $SecretId -and $MesCoreDbSecretId) {
    $SecretId = $MesCoreDbSecretId
}

$SshTarget = "${TestbedUser}@${TestbedHost}"
$SshArgs = @("-i", $SshKeyPath, "-o", "StrictHostKeyChecking=accept-new")
$RemoteApiDir = if ($RemoteApiDir) { $RemoteApiDir } else { "/home/ubuntu/nyra-mes-api" }
$RemoteApiService = if ($RemoteApiService) { $RemoteApiService } else { "nyra-mes-api" }
$RemoteApiPort = if ($RemoteApiPort) { $RemoteApiPort } else { "8010" }

$ScpArgs = @("-i", $SshKeyPath, "-o", "StrictHostKeyChecking=accept-new")

Write-Host "`n=== Sync testbed DB config (Secrets Manager) ===" -ForegroundColor Cyan

& scp @ScpArgs `
    (Join-Path $DeployDir "sync_testbed_db_env.sh") `
    (Join-Path $DeployDir "discover_rds_secret.py") `
    "${SshTarget}:${RemoteApiDir}/scripts/deploy/"

$secretArg = $SecretId
$remoteCmd = @(
    "set -e",
    "chmod +x $RemoteApiDir/scripts/deploy/sync_testbed_db_env.sh",
    "bash $RemoteApiDir/scripts/deploy/sync_testbed_db_env.sh '$RemoteApiDir' '$secretArg' '$RemoteApiService' '$RemoteApiPort'"
) -join "; "

& ssh @SshArgs $SshTarget $remoteCmd
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`nTestbed DB uses Secrets Manager - deploys no longer need manual password updates in .env." -ForegroundColor Green
