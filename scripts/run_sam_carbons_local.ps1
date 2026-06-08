# Activated Carbon — seed + API (legacy entry; prefer run_sam_carbons_stack.ps1 in nyra-mes-ui)
# Usage:
#   .\scripts\run_sam_carbons_local.ps1
#   .\scripts\run_sam_carbons_api.ps1 -Seed   # same seed, API only

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
& "$Root\scripts\run_sam_carbons_api.ps1" -Seed
