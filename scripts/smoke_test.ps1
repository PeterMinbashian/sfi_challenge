# Full endpoint smoke test for Freight Challenge API
# Prerequisite: API already running, e.g.
#   uvicorn app.main:app --host 127.0.0.1 --port 8000
#
# Run:
#   powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test.ps1 -BaseUrl http://127.0.0.1:8000

param(
    [string]$BaseUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"
$script:Pass = 0
$script:Fail = 0
$script:Results = @()

function Write-Result {
    param([string]$Name, [bool]$Ok, [string]$Detail = "")
    if ($Ok) {
        $script:Pass++
        Write-Host ("  PASS  {0}  {1}" -f $Name, $Detail) -ForegroundColor Green
        $script:Results += [pscustomobject]@{ Status = "PASS"; Name = $Name; Detail = $Detail }
    } else {
        $script:Fail++
        Write-Host ("  FAIL  {0}  {1}" -f $Name, $Detail) -ForegroundColor Red
        $script:Results += [pscustomobject]@{ Status = "FAIL"; Name = $Name; Detail = $Detail }
    }
}

function Invoke-Json {
    param(
        [string]$Method = "GET",
        [string]$Path,
        [string]$Body = $null
    )
    $uri = "$BaseUrl$Path"
    if ($Method -eq "GET") {
        return Invoke-RestMethod -Method GET -Uri $uri
    }
    if ($null -eq $Body) {
        return Invoke-RestMethod -Method $Method -Uri $uri -ContentType "application/json"
    }
    return Invoke-RestMethod -Method $Method -Uri $uri -ContentType "application/json" -Body $Body
}

function Invoke-ExpectStatus {
    param(
        [string]$Name,
        [string]$Method = "GET",
        [string]$Path,
        [string]$Body = "",
        [int[]]$Expected = @(200),
        [scriptblock]$ExtraCheck = $null
    )
    try {
        $uri = "$BaseUrl$Path"
        # Important: never send -Body on GET (PowerShell [string]$null becomes "")
        if ($Method -eq "GET") {
            $resp = Invoke-WebRequest -Method GET -Uri $uri -UseBasicParsing
        } else {
            $resp = Invoke-WebRequest -Method $Method -Uri $uri -UseBasicParsing `
                -ContentType "application/json" -Body $Body
        }
        $code = [int]$resp.StatusCode
        $ok = $Expected -contains $code
        $detail = "HTTP $code"
        $parsed = $null
        if ($resp.Content) {
            try { $parsed = $resp.Content | ConvertFrom-Json } catch { $parsed = $null }
        }
        if ($ok -and $ExtraCheck) {
            $checkDetail = & $ExtraCheck $parsed $resp
            if ($checkDetail -is [string] -and $checkDetail.StartsWith("FAIL:")) {
                $ok = $false
                $detail = "$detail; $checkDetail"
            } elseif ($checkDetail) {
                $detail = "$detail; $checkDetail"
            }
        }
        Write-Result -Name $Name -Ok $ok -Detail $detail
        return $parsed
    } catch {
        $code = $null
        if ($_.Exception.Response) {
            $code = [int]$_.Exception.Response.StatusCode
        }
        if ($code -and ($Expected -contains $code)) {
            Write-Result -Name $Name -Ok $true -Detail "HTTP $code (expected error)"
            return $null
        }
        Write-Result -Name $Name -Ok $false -Detail $_.Exception.Message
        return $null
    }
}

function Wait-OpenOrder {
    param(
        [string]$OrderType = "",
        [int]$TimeoutSec = 120,
        [string[]]$Exclude = @()
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if ($OrderType) {
            $path = "/orders?status=open&order_type=$OrderType"
        } else {
            $path = "/orders?status=open"
        }
        $raw = Invoke-Json -Path $path
        $orders = @()
        if ($null -ne $raw) {
            if ($raw -is [System.Array]) { $orders = @($raw) } else { $orders = @($raw) }
        }
        foreach ($o in $orders) {
            $id = [string]$o.external_id
            if ($id -and ($Exclude -notcontains $id)) {
                return ,$o
            }
        }
        Write-Host "  waiting for open order..."
        Start-Sleep -Seconds 2
    }
    throw "Timed out waiting for an open order on $BaseUrl"
}

function Get-OrderId {
    param($Order)
    if ($Order -is [System.Array]) { return [string]$Order[0].external_id }
    return [string]$Order.external_id
}

Write-Host ""
Write-Host "Freight Challenge API - full endpoint smoke test" -ForegroundColor Cyan
Write-Host "Base URL: $BaseUrl"
Write-Host "New orders arrive about every 60s - order action waits are normal."
Write-Host ""

# -------------------------------------------------------------------------
Write-Host "--- System ---" -ForegroundColor Cyan
Invoke-ExpectStatus -Name "GET /health" -Path "/health" -ExtraCheck {
    param($j, $r)
    if (-not $j.status -or $j.status -ne "ok") { return "FAIL: status not ok" }
    return "app=$($j.app)"
}

# -------------------------------------------------------------------------
Write-Host "`n--- Terminals ---" -ForegroundColor Cyan
$terminals = Invoke-ExpectStatus -Name "GET /terminals" -Path "/terminals" -ExtraCheck {
    param($j, $r)
    $arr = @($j)
    if ($arr.Count -lt 1) { return "FAIL: empty terminal list" }
    return "count=$($arr.Count)"
}
$sampleCode = "ATL"
if ($terminals) {
    $tarr = @($terminals)
    if ($tarr.Count -gt 0 -and $tarr[0].code) { $sampleCode = [string]$tarr[0].code }
}
Invoke-ExpectStatus -Name "GET /terminals/{code}" -Path "/terminals/$sampleCode" -ExtraCheck {
    param($j, $r)
    if ([string]$j.code -ne $sampleCode) { return "FAIL: code mismatch" }
    return "code=$($j.code) city=$($j.city)"
}
Invoke-ExpectStatus -Name "GET /terminals/{bad}" -Path "/terminals/ZZZ" -Expected @(404)

# -------------------------------------------------------------------------
Write-Host "`n--- Fleet ---" -ForegroundColor Cyan
Invoke-ExpectStatus -Name "GET /fleet/availability" -Path "/fleet/availability" -ExtraCheck {
    param($j, $r)
    $arr = @($j)
    if ($arr.Count -lt 1) { return "FAIL: empty" }
    if ($null -eq $arr[0].available_units) { return "FAIL: missing available_units" }
    return "terminals=$($arr.Count) first_available=$($arr[0].available_units)"
}
Invoke-ExpectStatus -Name "GET /fleet/availability?terminal_code=" -Path "/fleet/availability?terminal_code=$sampleCode" -ExtraCheck {
    param($j, $r)
    $arr = @($j)
    if ($arr.Count -ne 1) { return "FAIL: expected 1 row" }
    return "available_units=$($arr[0].available_units)"
}
Invoke-ExpectStatus -Name "GET /fleet/units" -Path "/fleet/units" -ExtraCheck {
    param($j, $r)
    return "count=$(@($j).Count)"
}
Invoke-ExpectStatus -Name "GET /fleet/units?terminal_code=&status=available" `
    -Path "/fleet/units?terminal_code=$sampleCode&status=available" -ExtraCheck {
    param($j, $r)
    return "count=$(@($j).Count)"
}
Invoke-ExpectStatus -Name "GET /fleet/drivers" -Path "/fleet/drivers" -ExtraCheck {
    param($j, $r)
    return "count=$(@($j).Count)"
}
Invoke-ExpectStatus -Name "GET /fleet/snapshot" -Path "/fleet/snapshot" -ExtraCheck {
    param($j, $r)
    $arr = @($j)
    if ($arr.Count -lt 1) { return "FAIL: empty snapshot" }
    if ($null -eq $arr[0].total_units) { return "FAIL: missing total_units" }
    return "terminals=$($arr.Count)"
}

# -------------------------------------------------------------------------
Write-Host "`n--- History ---" -ForegroundColor Cyan
Invoke-ExpectStatus -Name "GET /history/shipments" -Path "/history/shipments?limit=5" -ExtraCheck {
    param($j, $r)
    $arr = @($j)
    if ($arr.Count -lt 1) { return "FAIL: no shipments" }
    return "count=$($arr.Count)"
}
Invoke-ExpectStatus -Name "GET /history/lanes" -Path "/history/lanes" -ExtraCheck {
    param($j, $r)
    return "count=$(@($j).Count)"
}
try {
    $csvResp = Invoke-WebRequest -Method GET -Uri "$BaseUrl/history/shipments.csv" -UseBasicParsing
    $csvOk = ([int]$csvResp.StatusCode -eq 200) -and ($csvResp.Content -match "lane_id")
    Write-Result -Name "GET /history/shipments.csv" -Ok $csvOk -Detail ("HTTP {0}; bytes={1}" -f $csvResp.StatusCode, $csvResp.RawContentLength)
} catch {
    Write-Result -Name "GET /history/shipments.csv" -Ok $false -Detail $_.Exception.Message
}

# -------------------------------------------------------------------------
Write-Host "`n--- Simulation clock ---" -ForegroundColor Cyan
Invoke-ExpectStatus -Name "GET /simulation/clock" -Path "/simulation/clock" -ExtraCheck {
    param($j, $r)
    if ($null -eq $j.simulation_speed) { return "FAIL: missing simulation_speed" }
    return "speed=$($j.simulation_speed)"
}
Invoke-ExpectStatus -Name "POST /simulation/clock (speed=60)" -Method "POST" -Path "/simulation/clock" `
    -Body '{"simulation_speed": 60}' -ExtraCheck {
    param($j, $r)
    if ([double]$j.simulation_speed -ne 60) { return "FAIL: speed not 60" }
    return "speed=$($j.simulation_speed)"
}
Invoke-ExpectStatus -Name "POST /simulation/clock (restore speed=1)" -Method "POST" -Path "/simulation/clock" `
    -Body '{"simulation_speed": 1}' -ExtraCheck {
    param($j, $r)
    if ([double]$j.simulation_speed -ne 1) { return "FAIL: speed not 1" }
    return "speed=$($j.simulation_speed)"
}

# -------------------------------------------------------------------------
Write-Host "`n--- Orders (read) ---" -ForegroundColor Cyan
Invoke-ExpectStatus -Name "GET /orders" -Path "/orders?status=all" -ExtraCheck {
    param($j, $r)
    return "count=$(@($j).Count)"
}
Invoke-ExpectStatus -Name "GET /orders?status=open" -Path "/orders?status=open" -ExtraCheck {
    param($j, $r)
    return "count=$(@($j).Count)"
}

# -------------------------------------------------------------------------
Write-Host "`n--- Orders (accept / decline / bid) ---" -ForegroundColor Cyan
Write-Host "Fetching live order ids from the board (may take up to ~3 min at 60s interval)..."

try {
    $fixed = Wait-OpenOrder -OrderType "fixed_rate" -TimeoutSec 200
    $fixedId = Get-OrderId $fixed
    Write-Host "  found fixed_rate id: $fixedId"

    Invoke-ExpectStatus -Name "GET /orders/{external_id}" -Path "/orders/$fixedId" -ExtraCheck {
        param($j, $r)
        if ([string]$j.external_id -ne $fixedId) { return "FAIL: id mismatch" }
        return "id=$($j.external_id) type=$($j.order_type)"
    }

    $accept = Invoke-ExpectStatus -Name "POST /orders/{id}/accept" -Method "POST" `
        -Path "/orders/$fixedId/accept" -Body "{}" -ExtraCheck {
        param($j, $r)
        if (-not $j.ok) { return "FAIL: ok=false" }
        if ([string]$j.order.status -ne "accepted") { return "FAIL: status=$($j.order.status)" }
        return "status=accepted unit locked"
    }

    # Re-accept should conflict
    Invoke-ExpectStatus -Name "POST /orders/{id}/accept (already accepted -> 409)" -Method "POST" `
        -Path "/orders/$fixedId/accept" -Body "{}" -Expected @(409)

    $used = @($fixedId)
    $toDecline = Wait-OpenOrder -Exclude $used -TimeoutSec 200
    $declineId = Get-OrderId $toDecline
    Write-Host "  found decline id: $declineId"
    Invoke-ExpectStatus -Name "POST /orders/{id}/decline" -Method "POST" `
        -Path "/orders/$declineId/decline" -Body "{}" -ExtraCheck {
        param($j, $r)
        if ([string]$j.order.status -ne "declined") { return "FAIL: status=$($j.order.status)" }
        return "status=declined"
    }
    $used += $declineId

    $openBid = Wait-OpenOrder -OrderType "open_bid" -Exclude $used -TimeoutSec 200
    $bidId = Get-OrderId $openBid
    $miles = [double]([string]$openBid.distance_miles)
    $bidRate = [math]::Round($miles * 2.5, 2)
    Write-Host "  found open_bid id: $bidId  bidding $bidRate"
    $bidBody = (@{ bid_rate = $bidRate } | ConvertTo-Json)
    Invoke-ExpectStatus -Name "POST /orders/{id}/bid" -Method "POST" `
        -Path "/orders/$bidId/bid" -Body $bidBody -ExtraCheck {
        param($j, $r)
        if ([string]$j.order.status -ne "bid_submitted") { return "FAIL: status=$($j.order.status)" }
        return "status=bid_submitted"
    }

    # Wrong verb checks
    Invoke-ExpectStatus -Name "POST accept on open_bid -> 400" -Method "POST" `
        -Path "/orders/$bidId/accept" -Body "{}" -Expected @(400, 409)

    Invoke-Json -Method "POST" -Path "/simulation/clock" -Body '{"simulation_speed": 3600}' | Out-Null
    $final = $null
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        Invoke-Json -Path "/orders?status=all" | Out-Null
        $final = Invoke-Json -Path "/orders/$bidId"
        if ($final.status -eq "accepted" -or $final.status -eq "bid_lost") { break }
    }
    Invoke-Json -Method "POST" -Path "/simulation/clock" -Body '{"simulation_speed": 1}' | Out-Null
    $resolved = ($final.status -eq "accepted" -or $final.status -eq "bid_lost")
    Write-Result -Name "Bid shipper decision (accepted|bid_lost)" -Ok $resolved -Detail ("status={0}" -f $final.status)

} catch {
    Write-Result -Name "Order action flow" -Ok $false -Detail $_.Exception.Message
}

# -------------------------------------------------------------------------
Write-Host "`n--- WebSocket /orders/ws ---" -ForegroundColor Cyan
try {
    $wsUrl = ($BaseUrl -replace "^http", "ws") + "/orders/ws"
    $ws = [System.Net.WebSockets.ClientWebSocket]::new()
    $cts = [System.Threading.CancellationTokenSource]::new()
    $cts.CancelAfter(10000)
    $connectTask = $ws.ConnectAsync([Uri]$wsUrl, $cts.Token)
    $connectTask.Wait()
    $buffer = [byte[]]::new(8192)
    $segment = [ArraySegment[byte]]::new($buffer)
    $receiveTask = $ws.ReceiveAsync($segment, $cts.Token)
    $receiveTask.Wait()
    $text = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $receiveTask.Result.Count)
    $wsOk = $text -match "snapshot|order"
    Write-Result -Name "WS /orders/ws" -Ok $wsOk -Detail ("received {0} bytes" -f $receiveTask.Result.Count)
    $ws.Dispose()
} catch {
    Write-Result -Name "WS /orders/ws" -Ok $false -Detail $_.Exception.Message
}

# -------------------------------------------------------------------------
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ("SUMMARY: {0} passed, {1} failed" -f $script:Pass, $script:Fail)
Write-Host "========================================" -ForegroundColor Cyan
if ($script:Fail -gt 0) {
    Write-Host "Failed checks:" -ForegroundColor Red
    $script:Results | Where-Object { $_.Status -eq "FAIL" } | ForEach-Object {
        Write-Host ("  - {0}: {1}" -f $_.Name, $_.Detail)
    }
    exit 1
}
Write-Host "All endpoint checks passed." -ForegroundColor Green
exit 0
