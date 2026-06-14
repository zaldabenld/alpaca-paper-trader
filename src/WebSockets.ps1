Set-StrictMode -Version Latest

function Start-AlpacaTradeUpdateStream {
    param(
        [Parameter(Mandatory = $true)][string]$ApiKey,
        [Parameter(Mandatory = $true)][string]$SecretKey,
        [Parameter(Mandatory = $true)][string]$EventLogPath
    )

    Start-Job -Name 'AlpacaTradeUpdates' -ArgumentList $ApiKey, $SecretKey, $EventLogPath -ScriptBlock {
        param($ApiKey, $SecretKey, $EventLogPath)

        Add-Type -AssemblyName System.Web

        function Write-AppEvent {
            param(
                [string]$Type,
                [string]$Message,
                [AllowNull()]$Payload
            )

            $event = [PSCustomObject]@{
                time = [DateTimeOffset]::Now.ToString('o')
                source = 'trade_updates'
                type = $Type
                message = $Message
                payload = $Payload
            }

            $line = $event | ConvertTo-Json -Depth 20 -Compress
            Add-Content -LiteralPath $EventLogPath -Value $line -Encoding UTF8
        }

        function Send-JsonMessage {
            param(
                [System.Net.WebSockets.ClientWebSocket]$Socket,
                [hashtable]$Message
            )

            $json = $Message | ConvertTo-Json -Depth 12 -Compress
            $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
            $segment = [ArraySegment[byte]]::new($bytes)
            $Socket.SendAsync($segment, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
        }

        function Receive-TextMessage {
            param([System.Net.WebSockets.ClientWebSocket]$Socket)

            $buffer = New-Object byte[] 65536
            $stream = [System.IO.MemoryStream]::new()
            try {
                do {
                    $segment = [ArraySegment[byte]]::new($buffer)
                    $result = $Socket.ReceiveAsync($segment, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
                    if ($result.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close) {
                        return $null
                    }
                    $stream.Write($buffer, 0, $result.Count)
                } while (-not $result.EndOfMessage)

                [System.Text.Encoding]::UTF8.GetString($stream.ToArray())
            }
            finally {
                $stream.Dispose()
            }
        }

        while ($true) {
            $socket = [System.Net.WebSockets.ClientWebSocket]::new()
            try {
                $socket.ConnectAsync([Uri]'wss://paper-api.alpaca.markets/stream', [Threading.CancellationToken]::None).GetAwaiter().GetResult()
                Write-AppEvent -Type 'connected' -Message 'Trading websocket connected.' -Payload $null

                Send-JsonMessage -Socket $socket -Message @{
                    action = 'auth'
                    key = $ApiKey
                    secret = $SecretKey
                }

                Send-JsonMessage -Socket $socket -Message @{
                    action = 'listen'
                    data = @{
                        streams = @('trade_updates')
                    }
                }

                while ($socket.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
                    $text = Receive-TextMessage -Socket $socket
                    if ($null -eq $text) {
                        break
                    }

                    $payload = $null
                    try { $payload = $text | ConvertFrom-Json } catch { $payload = $text }

                    $eventName = 'message'
                    if ($payload -and $payload.PSObject.Properties['data'] -and $payload.data.PSObject.Properties['event']) {
                        $eventName = [string]$payload.data.event
                    }
                    elseif ($payload -and $payload.PSObject.Properties['stream']) {
                        $eventName = [string]$payload.stream
                    }

                    Write-AppEvent -Type $eventName -Message ('Trade stream: {0}' -f $eventName) -Payload $payload
                }
            }
            catch {
                Write-AppEvent -Type 'error' -Message $_.Exception.Message -Payload $null
                Start-Sleep -Seconds 5
            }
            finally {
                if ($socket) {
                    try { $socket.Dispose() } catch {}
                }
            }
        }
    }
}

function Start-AlpacaMarketDataStream {
    param(
        [Parameter(Mandatory = $true)][string]$ApiKey,
        [Parameter(Mandatory = $true)][string]$SecretKey,
        [Parameter(Mandatory = $true)][string[]]$Symbols,
        [ValidateSet('iex', 'sip', 'delayed_sip', 'otc', 'boats', 'overnight')][string]$Feed = 'iex',
        [Parameter(Mandatory = $true)][string]$EventLogPath
    )

    $cleanSymbols = @($Symbols | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { $_.Trim().ToUpperInvariant() } | Select-Object -Unique)

    Start-Job -Name 'AlpacaMarketBars' -ArgumentList $ApiKey, $SecretKey, (,$cleanSymbols), $Feed, $EventLogPath -ScriptBlock {
        param($ApiKey, $SecretKey, $Symbols, $Feed, $EventLogPath)

        function Write-AppEvent {
            param(
                [string]$Type,
                [string]$Message,
                [AllowNull()]$Payload
            )

            $event = [PSCustomObject]@{
                time = [DateTimeOffset]::Now.ToString('o')
                source = 'market_data'
                type = $Type
                message = $Message
                payload = $Payload
            }

            $line = $event | ConvertTo-Json -Depth 20 -Compress
            Add-Content -LiteralPath $EventLogPath -Value $line -Encoding UTF8
        }

        function Send-JsonMessage {
            param(
                [System.Net.WebSockets.ClientWebSocket]$Socket,
                [hashtable]$Message
            )

            $json = $Message | ConvertTo-Json -Depth 12 -Compress
            $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
            $segment = [ArraySegment[byte]]::new($bytes)
            $Socket.SendAsync($segment, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
        }

        function Receive-TextMessage {
            param([System.Net.WebSockets.ClientWebSocket]$Socket)

            $buffer = New-Object byte[] 65536
            $stream = [System.IO.MemoryStream]::new()
            try {
                do {
                    $segment = [ArraySegment[byte]]::new($buffer)
                    $result = $Socket.ReceiveAsync($segment, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
                    if ($result.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close) {
                        return $null
                    }
                    $stream.Write($buffer, 0, $result.Count)
                } while (-not $result.EndOfMessage)

                [System.Text.Encoding]::UTF8.GetString($stream.ToArray())
            }
            finally {
                $stream.Dispose()
            }
        }

        if (-not $Symbols -or $Symbols.Count -eq 0) {
            Write-AppEvent -Type 'error' -Message 'No symbols were provided for market-data streaming.' -Payload $null
            return
        }

        $versionFeed = if ($Feed -in @('boats', 'overnight')) { 'v1beta1/{0}' -f $Feed } else { 'v2/{0}' -f $Feed }
        $streamUri = 'wss://stream.data.alpaca.markets/{0}' -f $versionFeed

        while ($true) {
            $socket = [System.Net.WebSockets.ClientWebSocket]::new()
            try {
                $socket.ConnectAsync([Uri]$streamUri, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
                Write-AppEvent -Type 'connected' -Message ('Market-data websocket connected to {0}.' -f $Feed) -Payload $null

                Send-JsonMessage -Socket $socket -Message @{
                    action = 'auth'
                    key = $ApiKey
                    secret = $SecretKey
                }

                Send-JsonMessage -Socket $socket -Message @{
                    action = 'subscribe'
                    bars = @($Symbols)
                }

                while ($socket.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
                    $text = Receive-TextMessage -Socket $socket
                    if ($null -eq $text) {
                        break
                    }

                    $payload = $null
                    try { $payload = $text | ConvertFrom-Json } catch { $payload = $text }

                    $eventType = 'message'
                    if ($payload -is [array] -and $payload.Count -gt 0 -and $payload[0].PSObject.Properties['T']) {
                        $eventType = [string]$payload[0].T
                    }
                    elseif ($payload -isnot [array] -and $payload -and $payload.PSObject.Properties['T']) {
                        $eventType = [string]$payload.T
                    }

                    Write-AppEvent -Type $eventType -Message ('Market data: {0}' -f $eventType) -Payload $payload
                }
            }
            catch {
                Write-AppEvent -Type 'error' -Message $_.Exception.Message -Payload $null
                Start-Sleep -Seconds 5
            }
            finally {
                if ($socket) {
                    try { $socket.Dispose() } catch {}
                }
            }
        }
    }
}

function Stop-AlpacaStreamJobs {
    param([System.Management.Automation.Job[]]$Jobs)

    foreach ($job in @($Jobs)) {
        if ($null -eq $job) {
            continue
        }
        try {
            Stop-Job -Job $job -Force -ErrorAction SilentlyContinue
            Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
        }
        catch {}
    }
}
