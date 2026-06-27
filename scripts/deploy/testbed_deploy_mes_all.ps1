# Deploy nyra-mes-api + nyra-mes-ui to nyraservices-testbed.net/mes
#
# Prerequisites:
#   - deploy-config.ps1 (copy from deploy-config.ps1.example)
#   - OpenSSH scp/ssh, tar, npm
#   - PEM key with access to testbed EC2
#
# Usage:
#   cd d:\Sudha\Nyra\nyra-mes-api
#   .\scripts\deploy\testbed_deploy_mes_all.ps1

param(
    [switch]$ApiOnly,
    [switch]$UiOnly,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$DeployDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ApiRoot = Split-Path -Parent (Split-Path -Parent $DeployDir)
$UiRoot = Join-Path (Split-Path -Parent $ApiRoot) "nyra-mes-ui"
$ConfigPath = Join-Path $DeployDir "deploy-config.ps1"

if (-not (Test-Path $ConfigPath)) {
    Write-Host "ERROR: Create $ConfigPath from deploy-config.ps1.example" -ForegroundColor Red
    exit 1
}
. $ConfigPath

if (-not (Test-Path variable:RemoteApiPort) -or [string]::IsNullOrWhiteSpace($RemoteApiPort)) {
    $RemoteApiPort = "8010"
}

if (-not (Test-Path $SshKeyPath)) {
    Write-Host "ERROR: SSH key not found: $SshKeyPath" -ForegroundColor Red
    exit 1
}

$SshTarget = "${TestbedUser}@${TestbedHost}"
$SshArgs = @("-i", $SshKeyPath, "-o", "StrictHostKeyChecking=accept-new")
$ScpArgs = @("-i", $SshKeyPath, "-o", "StrictHostKeyChecking=accept-new")

function Invoke-Ssh([string[]]$RemoteCommand) {
    $script = ($RemoteCommand -join "; ")
    & ssh @SshArgs $SshTarget $script
    if ($LASTEXITCODE -ne 0) { throw "SSH failed: $script" }
}

function Invoke-Scp([string]$LocalPath, [string]$RemotePath) {
    & scp @ScpArgs $LocalPath "${SshTarget}:${RemotePath}"
    if ($LASTEXITCODE -ne 0) { throw "SCP failed: $LocalPath -> $RemotePath" }
}

if (-not $UiOnly) {
    Write-Host "`n=== Pack API ===" -ForegroundColor Cyan
    $ApiTar = Join-Path $env:TEMP "nyra-mes-api-deploy.tar.gz"
    if (Test-Path $ApiTar) { Remove-Item $ApiTar -Force }

    Push-Location $ApiRoot
    tar -czf $ApiTar `
        --exclude=venv `
        --exclude=__pycache__ `
        --exclude=.git `
        --exclude=.env `
        --exclude=.env.demo `
        --exclude=.env.production `
        --exclude="_deploy-api.tar.gz" `
        app database requirements.txt scripts tests
    Pop-Location
    Write-Host "Created $ApiTar"

    Write-Host "`n=== Upload API ===" -ForegroundColor Cyan
    Invoke-Scp $ApiTar "/tmp/nyra-mes-api-deploy.tar.gz"

    Write-Host "`n=== Install API on server ===" -ForegroundColor Cyan
    Invoke-Ssh @(
        "set -e",
        "mkdir -p $RemoteApiDir",
        "tar -xzf /tmp/nyra-mes-api-deploy.tar.gz -C $RemoteApiDir",
        "chmod +x $RemoteApiDir/scripts/deploy/remote-deploy-api.sh",
        "chmod +x $RemoteApiDir/scripts/deploy/sync_testbed_db_env.sh",
        "bash $RemoteApiDir/scripts/deploy/remote-deploy-api.sh $RemoteApiDir $RemoteApiService $RemoteApiPort"
    )
}

if (-not $ApiOnly) {
    if (-not (Test-Path $UiRoot)) {
        Write-Host "ERROR: UI repo not found at $UiRoot" -ForegroundColor Red
        exit 1
    }

    if (-not $SkipBuild) {
        Write-Host "`n=== Build UI (production) ===" -ForegroundColor Cyan
        Push-Location $UiRoot
        if (-not (Test-Path "node_modules")) {
            npm ci
        }
        npm run build -- --mode production
        Pop-Location
    }

    $DistDir = Join-Path $UiRoot "dist"
    if (-not (Test-Path $DistDir)) {
        Write-Host "ERROR: dist/ missing - run npm run build -- --mode production" -ForegroundColor Red
        exit 1
    }

    Write-Host "`n=== Pack UI ===" -ForegroundColor Cyan
    $UiTar = Join-Path $env:TEMP "nyra-mes-ui-dist.tar.gz"
    if (Test-Path $UiTar) { Remove-Item $UiTar -Force }
    Push-Location $DistDir
    tar -czf $UiTar .
    Pop-Location

    Write-Host "`n=== Upload UI ===" -ForegroundColor Cyan
    Invoke-Ssh @("mkdir -p /tmp/nyra-mes-ui-dist")
    Invoke-Scp $UiTar "/tmp/nyra-mes-ui-dist.tar.gz"
    Invoke-Scp (Join-Path $DeployDir "remote-deploy-ui.sh") "/tmp/remote-deploy-ui.sh"
    Invoke-Ssh @(
        "set -e",
        "rm -rf /tmp/nyra-mes-ui-dist",
        "mkdir -p /tmp/nyra-mes-ui-dist",
        "tar -xzf /tmp/nyra-mes-ui-dist.tar.gz -C /tmp/nyra-mes-ui-dist",
        "chmod +x /tmp/remote-deploy-ui.sh",
        "bash /tmp/remote-deploy-ui.sh $RemoteUiDir /tmp/nyra-mes-ui-dist"
    )
}

Write-Host "`n=== Verify testbed ===" -ForegroundColor Green
Write-Host "  https://nyraservices-testbed.net/mes/api/"
Write-Host "  https://nyraservices-testbed.net/mes/api/auth/host-config?host=nyraservices-testbed.net"
Write-Host "  https://nyraservices-testbed.net/mes/activated-carbon/dashboard"
Write-Host ""
