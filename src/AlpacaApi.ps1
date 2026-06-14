Set-StrictMode -Version Latest

Add-Type -AssemblyName System.Net.Http

$script:PaperTradingBaseUrl = 'https://paper-api.alpaca.markets'
$script:MarketDataBaseUrl = 'https://data.alpaca.markets'

function New-AlpacaSession {
    param(
        [Parameter(Mandatory = $true)][string]$ApiKey,
        [Parameter(Mandatory = $true)][string]$SecretKey
    )

    [PSCustomObject]@{
        ApiKey = $ApiKey.Trim()
        SecretKey = $SecretKey.Trim()
        TradingBaseUrl = $script:PaperTradingBaseUrl
        DataBaseUrl = $script:MarketDataBaseUrl
        CreatedAt = [DateTimeOffset]::Now
    }
}

function ConvertTo-AlpacaQueryString {
    param([hashtable]$Query)

    if (-not $Query -or $Query.Count -eq 0) {
        return ''
    }

    $pairs = New-Object System.Collections.Generic.List[string]
    foreach ($key in $Query.Keys) {
        $value = $Query[$key]
        if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) {
            continue
        }

        $encodedKey = [System.Net.WebUtility]::UrlEncode([string]$key)
        $encodedValue = [System.Net.WebUtility]::UrlEncode([string]$value)
        $pairs.Add(('{0}={1}' -f $encodedKey, $encodedValue))
    }

    [string]::Join('&', $pairs)
}

function ConvertTo-AlpacaDecimal {
    param(
        [AllowNull()]$Value,
        [decimal]$Default = 0
    )

    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) {
        return $Default
    }

    $styles = [System.Globalization.NumberStyles]::Any
    $culture = [System.Globalization.CultureInfo]::InvariantCulture
    $result = [decimal]0
    if ([decimal]::TryParse(([string]$Value), $styles, $culture, [ref]$result)) {
        return $result
    }

    return $Default
}

function Format-AlpacaNumber {
    param(
        [Parameter(Mandatory = $true)][decimal]$Value,
        [int]$DecimalPlaces = 4
    )

    $rounded = [Math]::Round($Value, $DecimalPlaces)
    $rounded.ToString("0.$(('0' * $DecimalPlaces))", [System.Globalization.CultureInfo]::InvariantCulture).TrimEnd('0').TrimEnd('.')
}

function Invoke-AlpacaRequest {
    param(
        [Parameter(Mandatory = $true)]$Session,
        [ValidateSet('Trading', 'Data')][string]$Api = 'Trading',
        [ValidateSet('GET', 'POST', 'DELETE')][string]$Method = 'GET',
        [Parameter(Mandatory = $true)][string]$Path,
        [hashtable]$Query,
        [AllowNull()]$Body
    )

    if (-not $Session.ApiKey -or -not $Session.SecretKey) {
        throw 'Missing Alpaca API credentials.'
    }

    $baseUrl = if ($Api -eq 'Data') { $Session.DataBaseUrl } else { $Session.TradingBaseUrl }
    $queryString = ConvertTo-AlpacaQueryString -Query $Query
    $uri = '{0}{1}' -f $baseUrl, $Path
    if ($queryString) {
        $uri = '{0}?{1}' -f $uri, $queryString
    }

    $httpMethod = switch ($Method) {
        'GET' { [System.Net.Http.HttpMethod]::Get }
        'POST' { [System.Net.Http.HttpMethod]::Post }
        'DELETE' { [System.Net.Http.HttpMethod]::Delete }
    }

    $client = [System.Net.Http.HttpClient]::new()
    $request = [System.Net.Http.HttpRequestMessage]::new($httpMethod, $uri)
    $null = $request.Headers.TryAddWithoutValidation('APCA-API-KEY-ID', $Session.ApiKey)
    $null = $request.Headers.TryAddWithoutValidation('APCA-API-SECRET-KEY', $Session.SecretKey)
    $null = $request.Headers.TryAddWithoutValidation('Accept', 'application/json')

    if ($null -ne $Body) {
        $json = $Body | ConvertTo-Json -Depth 12 -Compress
        $request.Content = [System.Net.Http.StringContent]::new($json, [System.Text.Encoding]::UTF8, 'application/json')
    }

    try {
        $response = $client.SendAsync($request).GetAwaiter().GetResult()
        $content = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()

        if (-not $response.IsSuccessStatusCode) {
            $requestId = ''
            if ($response.Headers.Contains('X-Request-ID')) {
                $requestId = ($response.Headers.GetValues('X-Request-ID') | Select-Object -First 1)
            }

            $detail = if ($content) { $content } else { $response.ReasonPhrase }
            if ($requestId) {
                throw ('Alpaca {0} {1} failed: HTTP {2}. Request ID: {3}. {4}' -f $Method, $Path, [int]$response.StatusCode, $requestId, $detail)
            }

            throw ('Alpaca {0} {1} failed: HTTP {2}. {3}' -f $Method, $Path, [int]$response.StatusCode, $detail)
        }

        if ([string]::IsNullOrWhiteSpace($content)) {
            return $null
        }

        return ($content | ConvertFrom-Json)
    }
    finally {
        if ($request) { $request.Dispose() }
        if ($client) { $client.Dispose() }
    }
}

function Get-AlpacaAccount {
    param([Parameter(Mandatory = $true)]$Session)
    Invoke-AlpacaRequest -Session $Session -Api Trading -Method GET -Path '/v2/account'
}

function Get-AlpacaClock {
    param([Parameter(Mandatory = $true)]$Session)
    Invoke-AlpacaRequest -Session $Session -Api Trading -Method GET -Path '/v2/clock'
}

function Get-AlpacaPositions {
    param([Parameter(Mandatory = $true)]$Session)
    @(Invoke-AlpacaRequest -Session $Session -Api Trading -Method GET -Path '/v2/positions')
}

function Get-AlpacaOrders {
    param(
        [Parameter(Mandatory = $true)]$Session,
        [ValidateSet('open', 'closed', 'all')][string]$Status = 'open',
        [int]$Limit = 50
    )

    @(Invoke-AlpacaRequest -Session $Session -Api Trading -Method GET -Path '/v2/orders' -Query @{
        status = $Status
        limit = $Limit
        nested = 'true'
        direction = 'desc'
    })
}

function Get-AlpacaBars {
    param(
        [Parameter(Mandatory = $true)]$Session,
        [Parameter(Mandatory = $true)][string[]]$Symbols,
        [ValidateSet('iex', 'sip', 'delayed_sip', 'otc', 'boats', 'overnight')][string]$Feed = 'iex',
        [string]$Timeframe = '1Min',
        [int]$Limit = 200
    )

    $cleanSymbols = @($Symbols | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { $_.Trim().ToUpperInvariant() } | Select-Object -Unique)
    if ($cleanSymbols.Count -eq 0) {
        throw 'At least one symbol is required for market data.'
    }

    Invoke-AlpacaRequest -Session $Session -Api Data -Method GET -Path '/v2/stocks/bars' -Query @{
        symbols = [string]::Join(',', $cleanSymbols)
        timeframe = $Timeframe
        feed = $Feed
        limit = [Math]::Max($Limit, $cleanSymbols.Count)
        adjustment = 'raw'
        sort = 'asc'
    }
}

function Get-AlpacaLatestBars {
    param(
        [Parameter(Mandatory = $true)]$Session,
        [Parameter(Mandatory = $true)][string[]]$Symbols,
        [ValidateSet('iex', 'sip', 'delayed_sip', 'otc', 'boats', 'overnight')][string]$Feed = 'iex'
    )

    $cleanSymbols = @($Symbols | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { $_.Trim().ToUpperInvariant() } | Select-Object -Unique)
    if ($cleanSymbols.Count -eq 0) {
        throw 'At least one symbol is required for latest bars.'
    }

    Invoke-AlpacaRequest -Session $Session -Api Data -Method GET -Path '/v2/stocks/bars/latest' -Query @{
        symbols = [string]::Join(',', $cleanSymbols)
        feed = $Feed
    }
}

function Submit-AlpacaOrder {
    param(
        [Parameter(Mandatory = $true)]$Session,
        [Parameter(Mandatory = $true)][hashtable]$Order
    )

    Invoke-AlpacaRequest -Session $Session -Api Trading -Method POST -Path '/v2/orders' -Body $Order
}

function Cancel-AlpacaOrders {
    param([Parameter(Mandatory = $true)]$Session)
    Invoke-AlpacaRequest -Session $Session -Api Trading -Method DELETE -Path '/v2/orders'
}
