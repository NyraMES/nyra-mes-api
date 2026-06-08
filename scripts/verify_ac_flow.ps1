# Quick Activated Carbon flow verification (requires API on :8000)
$Headers = @{
    "X-Tenant-Code"     = "SAM_CARBONS"
    "X-Workspace-Code"  = "SAM_CARBONS_ACTIVATED_CARBON"
}
$Base = "http://127.0.0.1:8000"

function Test-Endpoint($Name, $Url, $Method = "GET") {
    try {
        if ($Method -eq "GET") {
            $r = Invoke-RestMethod -Uri $Url -Headers $Headers -Method GET
        } else {
            $r = Invoke-RestMethod -Uri $Url -Headers $Headers -Method $Method -ContentType "application/json" -Body "{}"
        }
        $count = if ($r -is [Array]) { $r.Count } else { 1 }
        Write-Host "OK  $Name ($count items)" -ForegroundColor Green
        return $r
    } catch {
        Write-Host "FAIL $Name — $($_.Exception.Message)" -ForegroundColor Red
        return $null
    }
}

Write-Host "`n=== AC flow endpoint check ===" -ForegroundColor Cyan
Test-Endpoint "Context" "$Base/api/context"
Test-Endpoint "Masters" "$Base/api/activated-carbon/masters"
$inward = Test-Endpoint "Raw material inward" "$Base/api/activated-carbon/raw-material-inward"
$qc = Test-Endpoint "Raw material QC" "$Base/api/activated-carbon/raw-material-qc"
Test-Endpoint "Kiln feed lots" "$Base/api/activated-carbon/kiln-feed"
Test-Endpoint "Kiln parameters" "$Base/api/activated-carbon/kiln-parameters"
Test-Endpoint "Screening" "$Base/api/activated-carbon/screening"
Test-Endpoint "Quality testing" "$Base/api/activated-carbon/quality-testing"
Test-Endpoint "Yield" "$Base/api/activated-carbon/yield-analysis"
Test-Endpoint "Dispatch (legacy)" "$Base/api/activated-carbon/dispatches"
Test-Endpoint "Dispatch (trn)" "$Base/api/activated-carbon/dispatch"
Test-Endpoint "Dashboard" "$Base/api/activated-carbon/dashboard"

Write-Host "`nRaw inward orders:" -ForegroundColor Yellow
if ($inward) { $inward | ForEach-Object { Write-Host "  $($_.order_code) — lines: $($_.lines.Count)" } }
Write-Host "`nQC dropdown rows:" -ForegroundColor Yellow
if ($qc) { $qc | ForEach-Object { Write-Host "  $($_.order_code) / $($_.product_code) / $($_.qc_status)" } }
else { Write-Host "  (empty or endpoint missing - restart API and re-seed)" -ForegroundColor DarkYellow }
