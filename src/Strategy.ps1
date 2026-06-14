Set-StrictMode -Version Latest

function Get-CleanSymbolList {
    param([string]$SymbolsCsv)

    @($SymbolsCsv -split ',' |
        ForEach-Object { $_.Trim().ToUpperInvariant() } |
        Where-Object { $_ -match '^[A-Z0-9\.\-]+$' } |
        Select-Object -Unique)
}

function New-StrategyState {
    [PSCustomObject]@{
        Histories = @{}
        LastTradeAt = @{}
        LastAction = @{}
        LastBias = @{}
    }
}

function Get-SimpleMovingAverage {
    param(
        [Parameter(Mandatory = $true)][decimal[]]$Values,
        [Parameter(Mandatory = $true)][int]$Period
    )

    if ($Period -le 0 -or $Values.Count -lt $Period) {
        return $null
    }

    $slice = $Values[($Values.Count - $Period)..($Values.Count - 1)]
    $total = [decimal]0
    foreach ($value in $slice) {
        $total += $value
    }

    $total / $Period
}

function Add-StrategyBar {
    param(
        [Parameter(Mandatory = $true)]$State,
        [Parameter(Mandatory = $true)][string]$Symbol,
        [Parameter(Mandatory = $true)]$Bar,
        [int]$MaxBars = 500
    )

    $cleanSymbol = $Symbol.Trim().ToUpperInvariant()
    if (-not $State.Histories.ContainsKey($cleanSymbol)) {
        $State.Histories[$cleanSymbol] = @()
    }

    $close = ConvertTo-AlpacaDecimal -Value $Bar.c -Default 0
    if ($close -le 0) {
        return
    }

    $time = if ($Bar.PSObject.Properties['t']) { [string]$Bar.t } else { [DateTimeOffset]::Now.ToString('o') }
    $current = @($State.Histories[$cleanSymbol])
    if ($current.Count -gt 0 -and $current[-1].Time -eq $time) {
        $current[$current.Count - 1] = [PSCustomObject]@{ Time = $time; Close = $close }
    }
    else {
        $current += [PSCustomObject]@{ Time = $time; Close = $close }
    }

    if ($current.Count -gt $MaxBars) {
        $current = $current[($current.Count - $MaxBars)..($current.Count - 1)]
    }

    $State.Histories[$cleanSymbol] = $current
}

function Add-StrategyBarsFromResponse {
    param(
        [Parameter(Mandatory = $true)]$State,
        [Parameter(Mandatory = $true)]$BarsResponse,
        [Parameter(Mandatory = $true)][string[]]$Symbols
    )

    if ($null -eq $BarsResponse -or -not $BarsResponse.PSObject.Properties['bars']) {
        return
    }

    foreach ($symbol in $Symbols) {
        $cleanSymbol = $symbol.Trim().ToUpperInvariant()
        $property = $BarsResponse.bars.PSObject.Properties[$cleanSymbol]
        if ($null -eq $property) {
            continue
        }

        foreach ($bar in @($property.Value)) {
            Add-StrategyBar -State $State -Symbol $cleanSymbol -Bar $bar
        }
    }
}

function Get-StrategySnapshot {
    param(
        [Parameter(Mandatory = $true)]$State,
        [Parameter(Mandatory = $true)][string]$Symbol,
        [int]$ShortPeriod = 9,
        [int]$LongPeriod = 21
    )

    $cleanSymbol = $Symbol.Trim().ToUpperInvariant()
    $history = if ($State.Histories.ContainsKey($cleanSymbol)) { @($State.Histories[$cleanSymbol]) } else { @() }
    $values = @($history | ForEach-Object { [decimal]$_.Close })
    $price = if ($values.Count -gt 0) { $values[-1] } else { $null }
    $short = Get-SimpleMovingAverage -Values $values -Period $ShortPeriod
    $long = Get-SimpleMovingAverage -Values $values -Period $LongPeriod

    $bias = 'Waiting'
    if ($null -ne $short -and $null -ne $long) {
        if ($short -gt $long) { $bias = 'Bullish' }
        elseif ($short -lt $long) { $bias = 'Bearish' }
        else { $bias = 'Neutral' }
    }

    [PSCustomObject]@{
        Symbol = $cleanSymbol
        Price = $price
        ShortSma = $short
        LongSma = $long
        Bias = $bias
        Bars = $values.Count
        LastAction = if ($State.LastAction.ContainsKey($cleanSymbol)) { $State.LastAction[$cleanSymbol] } else { '' }
    }
}

function Get-PositionMap {
    param([AllowNull()]$Positions)

    $map = @{}
    foreach ($position in @($Positions)) {
        if ($null -eq $position -or -not $position.PSObject.Properties['symbol']) {
            continue
        }

        $map[[string]$position.symbol] = $position
    }

    $map
}

function Test-StrategyCooldown {
    param(
        [Parameter(Mandatory = $true)]$State,
        [Parameter(Mandatory = $true)][string]$Symbol,
        [int]$CooldownMinutes
    )

    if ($CooldownMinutes -le 0) {
        return $false
    }

    $cleanSymbol = $Symbol.Trim().ToUpperInvariant()
    if (-not $State.LastTradeAt.ContainsKey($cleanSymbol)) {
        return $false
    }

    $elapsed = [DateTimeOffset]::Now - [DateTimeOffset]$State.LastTradeAt[$cleanSymbol]
    $elapsed.TotalMinutes -lt $CooldownMinutes
}

function New-StrategyOrder {
    param(
        [Parameter(Mandatory = $true)][string]$Symbol,
        [Parameter(Mandatory = $true)][ValidateSet('buy', 'sell')][string]$Side,
        [Parameter(Mandatory = $true)][decimal]$Quantity,
        [decimal]$ReferencePrice,
        [decimal]$TakeProfitPercent,
        [decimal]$StopLossPercent,
        [switch]$UseBracket
    )

    $order = @{
        symbol = $Symbol.Trim().ToUpperInvariant()
        qty = (Format-AlpacaNumber -Value $Quantity -DecimalPlaces 4)
        side = $Side
        type = 'market'
        time_in_force = 'day'
        client_order_id = ('apt-{0}-{1}-{2}' -f $Side, $Symbol.Trim().ToLowerInvariant(), [DateTimeOffset]::Now.ToUnixTimeMilliseconds())
    }

    if ($UseBracket -and $Side -eq 'buy' -and $ReferencePrice -gt 0 -and ($TakeProfitPercent -gt 0 -or $StopLossPercent -gt 0)) {
        $order.order_class = 'bracket'

        if ($TakeProfitPercent -gt 0) {
            $takeProfit = $ReferencePrice * (1 + ($TakeProfitPercent / 100))
            $order.take_profit = @{
                limit_price = (Format-AlpacaNumber -Value $takeProfit -DecimalPlaces 2)
            }
        }

        if ($StopLossPercent -gt 0) {
            $stopLoss = $ReferencePrice * (1 - ($StopLossPercent / 100))
            $order.stop_loss = @{
                stop_price = (Format-AlpacaNumber -Value $stopLoss -DecimalPlaces 2)
            }
        }
    }

    $order
}

function Invoke-StrategyDecision {
    param(
        [Parameter(Mandatory = $true)]$State,
        [Parameter(Mandatory = $true)]$Session,
        [Parameter(Mandatory = $true)]$Config,
        [Parameter(Mandatory = $true)][string]$Symbol,
        [AllowNull()]$Position,
        [Parameter(Mandatory = $true)]$Account,
        [switch]$TradingEnabled
    )

    $events = New-Object System.Collections.Generic.List[object]
    $snapshot = Get-StrategySnapshot -State $State -Symbol $Symbol -ShortPeriod $Config.ShortPeriod -LongPeriod $Config.LongPeriod
    $cleanSymbol = $snapshot.Symbol

    if (-not $TradingEnabled) {
        return [PSCustomObject]@{ Snapshot = $snapshot; Events = $events; StopTrading = $false }
    }

    if ($snapshot.Bias -eq 'Waiting' -or $null -eq $snapshot.Price) {
        return [PSCustomObject]@{ Snapshot = $snapshot; Events = $events; StopTrading = $false }
    }

    if (Test-StrategyCooldown -State $State -Symbol $cleanSymbol -CooldownMinutes $Config.CooldownMinutes) {
        return [PSCustomObject]@{ Snapshot = $snapshot; Events = $events; StopTrading = $false }
    }

    $equity = ConvertTo-AlpacaDecimal -Value $Account.equity
    $lastEquity = ConvertTo-AlpacaDecimal -Value $Account.last_equity
    $dailyPl = $equity - $lastEquity
    if ($Config.DailyLossLimit -gt 0 -and $dailyPl -le (-1 * $Config.DailyLossLimit)) {
        $events.Add([PSCustomObject]@{
            Level = 'warn'
            Message = ('Daily loss limit reached. Daily P/L is {0:C2}; auto trading stopped.' -f $dailyPl)
        })
        return [PSCustomObject]@{ Snapshot = $snapshot; Events = $events; StopTrading = $true }
    }

    $qty = if ($null -ne $Position) { ConvertTo-AlpacaDecimal -Value $Position.qty } else { [decimal]0 }
    $marketValue = if ($null -ne $Position) { [Math]::Abs((ConvertTo-AlpacaDecimal -Value $Position.market_value)) } else { [decimal]0 }
    $hasLongPosition = $qty -gt 0

    if ($snapshot.Bias -eq 'Bullish' -and -not $hasLongPosition) {
        if ($Config.MaxOpenPositions -gt 0 -and $Config.CurrentOpenPositions -ge $Config.MaxOpenPositions) {
            $events.Add([PSCustomObject]@{ Level = 'info'; Message = ('Skipped {0}: max open positions limit is already reached.' -f $cleanSymbol) })
            return [PSCustomObject]@{ Snapshot = $snapshot; Events = $events; StopTrading = $false }
        }

        $buyingPower = ConvertTo-AlpacaDecimal -Value $Account.buying_power
        $tradeNotional = [Math]::Min($Config.MaxTradeNotional, $buyingPower)
        if ($Config.MaxPositionNotional -gt 0) {
            $tradeNotional = [Math]::Min($tradeNotional, $Config.MaxPositionNotional)
        }

        if ($tradeNotional -le 0) {
            $events.Add([PSCustomObject]@{ Level = 'warn'; Message = ('Skipped {0}: no buying power available.' -f $cleanSymbol) })
            return [PSCustomObject]@{ Snapshot = $snapshot; Events = $events; StopTrading = $false }
        }

        $quantity = [Math]::Round(($tradeNotional / $snapshot.Price), 4)
        if ($quantity -le 0) {
            $events.Add([PSCustomObject]@{ Level = 'warn'; Message = ('Skipped {0}: calculated quantity is zero.' -f $cleanSymbol) })
            return [PSCustomObject]@{ Snapshot = $snapshot; Events = $events; StopTrading = $false }
        }

        $order = New-StrategyOrder -Symbol $cleanSymbol -Side buy -Quantity $quantity -ReferencePrice $snapshot.Price -TakeProfitPercent $Config.TakeProfitPercent -StopLossPercent $Config.StopLossPercent -UseBracket:($Config.UseBracketOrders)
        if ($Config.DryRun) {
            $events.Add([PSCustomObject]@{ Level = 'info'; Message = ('Dry run: would buy {0} shares of {1}.' -f $order.qty, $cleanSymbol) })
        }
        else {
            $submitted = Submit-AlpacaOrder -Session $Session -Order $order
            $events.Add([PSCustomObject]@{ Level = 'success'; Message = ('Submitted buy order for {0}: {1}' -f $cleanSymbol, $submitted.id) })
        }

        $State.LastTradeAt[$cleanSymbol] = [DateTimeOffset]::Now
        $State.LastAction[$cleanSymbol] = 'Buy submitted'
    }
    elseif ($snapshot.Bias -eq 'Bearish' -and $hasLongPosition) {
        $quantity = [Math]::Abs($qty)
        $order = New-StrategyOrder -Symbol $cleanSymbol -Side sell -Quantity $quantity
        if ($Config.DryRun) {
            $events.Add([PSCustomObject]@{ Level = 'info'; Message = ('Dry run: would sell {0} shares of {1}.' -f $order.qty, $cleanSymbol) })
        }
        else {
            $submitted = Submit-AlpacaOrder -Session $Session -Order $order
            $events.Add([PSCustomObject]@{ Level = 'success'; Message = ('Submitted sell order for {0}: {1}' -f $cleanSymbol, $submitted.id) })
        }

        $State.LastTradeAt[$cleanSymbol] = [DateTimeOffset]::Now
        $State.LastAction[$cleanSymbol] = 'Sell submitted'
    }
    else {
        $State.LastAction[$cleanSymbol] = ('Hold ({0})' -f $snapshot.Bias)
    }

    $snapshot = Get-StrategySnapshot -State $State -Symbol $Symbol -ShortPeriod $Config.ShortPeriod -LongPeriod $Config.LongPeriod
    [PSCustomObject]@{ Snapshot = $snapshot; Events = $events; StopTrading = $false }
}
