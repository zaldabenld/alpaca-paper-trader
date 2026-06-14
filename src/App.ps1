param(
    [switch]$SmokeTest,
    [switch]$ValidateUi
)

Set-StrictMode -Version Latest

$ErrorActionPreference = 'Stop'
$script:RootDir = Split-Path -Parent $PSScriptRoot

. (Join-Path $PSScriptRoot 'AlpacaApi.ps1')
. (Join-Path $PSScriptRoot 'Strategy.ps1')
. (Join-Path $PSScriptRoot 'WebSockets.ps1')

if ($SmokeTest) {
    'Alpaca Paper Trader modules loaded.'
    return
}

Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase
Add-Type -AssemblyName System.Xaml

$script:AppDataDir = Join-Path $env:LOCALAPPDATA 'AlpacaPaperTrader'
$script:SettingsPath = Join-Path $script:AppDataDir 'settings.json'
$script:EventLogPath = Join-Path $script:AppDataDir 'events.jsonl'
New-Item -ItemType Directory -Force -Path $script:AppDataDir | Out-Null
Set-Content -LiteralPath $script:EventLogPath -Value '' -Encoding UTF8

$script:Session = $null
$script:StrategyState = New-StrategyState
$script:StreamJobs = @()
$script:TradingEnabled = $false
$script:IsRefreshing = $false
$script:EventLogOffset = 0
$script:PositionsRows = New-Object 'System.Collections.ObjectModel.ObservableCollection[object]'
$script:OrdersRows = New-Object 'System.Collections.ObjectModel.ObservableCollection[object]'
$script:StrategyRows = New-Object 'System.Collections.ObjectModel.ObservableCollection[object]'

$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Alpaca Paper Trader" Height="880" Width="1240" MinHeight="760" MinWidth="1040"
        WindowStartupLocation="CenterScreen" Background="#F4F7F9" FontFamily="Segoe UI">
    <Window.Resources>
        <Style TargetType="TextBlock">
            <Setter Property="Foreground" Value="#17202A"/>
        </Style>
        <Style TargetType="TextBox">
            <Setter Property="Margin" Value="0,4,0,10"/>
            <Setter Property="Padding" Value="8,6"/>
            <Setter Property="BorderBrush" Value="#C8D0D8"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Background" Value="White"/>
        </Style>
        <Style TargetType="PasswordBox">
            <Setter Property="Margin" Value="0,4,0,10"/>
            <Setter Property="Padding" Value="8,6"/>
            <Setter Property="BorderBrush" Value="#C8D0D8"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Background" Value="White"/>
        </Style>
        <Style TargetType="ComboBox">
            <Setter Property="Margin" Value="0,4,0,10"/>
            <Setter Property="Padding" Value="6,4"/>
        </Style>
        <Style TargetType="CheckBox">
            <Setter Property="Margin" Value="0,4,0,8"/>
            <Setter Property="Foreground" Value="#26323F"/>
        </Style>
        <Style TargetType="Button">
            <Setter Property="Margin" Value="0,4,8,4"/>
            <Setter Property="Padding" Value="12,8"/>
            <Setter Property="MinHeight" Value="34"/>
            <Setter Property="Background" Value="#1F7A65"/>
            <Setter Property="Foreground" Value="White"/>
            <Setter Property="BorderBrush" Value="#17624F"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Cursor" Value="Hand"/>
        </Style>
        <Style TargetType="GroupBox">
            <Setter Property="Margin" Value="0,0,0,14"/>
            <Setter Property="Padding" Value="12"/>
            <Setter Property="BorderBrush" Value="#D6DEE6"/>
            <Setter Property="Foreground" Value="#17202A"/>
            <Setter Property="Background" Value="#FFFFFF"/>
        </Style>
        <Style TargetType="DataGrid">
            <Setter Property="AutoGenerateColumns" Value="False"/>
            <Setter Property="CanUserAddRows" Value="False"/>
            <Setter Property="IsReadOnly" Value="True"/>
            <Setter Property="GridLinesVisibility" Value="Horizontal"/>
            <Setter Property="HeadersVisibility" Value="Column"/>
            <Setter Property="AlternatingRowBackground" Value="#F4F7F9"/>
            <Setter Property="RowBackground" Value="White"/>
            <Setter Property="BorderBrush" Value="#D6DEE6"/>
            <Setter Property="BorderThickness" Value="1"/>
        </Style>
    </Window.Resources>

    <Grid>
        <Grid.RowDefinitions>
            <RowDefinition Height="72"/>
            <RowDefinition Height="*"/>
        </Grid.RowDefinitions>

        <Border Grid.Row="0" Background="#17202A">
            <Grid Margin="24,0">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <StackPanel VerticalAlignment="Center">
                    <TextBlock Text="Alpaca Paper Trader" Foreground="White" FontSize="24" FontWeight="SemiBold"/>
                    <TextBlock Text="Paper REST orders, trade-update websocket, market-data websocket, configurable risk controls" Foreground="#C7D2DE" FontSize="12"/>
                </StackPanel>
                <Border Grid.Column="1" CornerRadius="4" Background="#DFF5EC" Padding="12,7" VerticalAlignment="Center">
                    <TextBlock Text="PAPER API ONLY" Foreground="#126B55" FontWeight="SemiBold"/>
                </Border>
            </Grid>
        </Border>

        <Grid Grid.Row="1" Margin="18">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="330"/>
                <ColumnDefinition Width="18"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>

            <ScrollViewer Grid.Column="0" VerticalScrollBarVisibility="Auto">
                <StackPanel>
                    <GroupBox Header="Credentials">
                        <StackPanel>
                            <TextBlock Text="API key"/>
                            <TextBox x:Name="ApiKeyBox"/>
                            <TextBlock Text="Secret key"/>
                            <PasswordBox x:Name="SecretBox"/>
                            <CheckBox x:Name="RememberKeysBox" Content="Remember encrypted on this Windows user"/>
                            <WrapPanel>
                                <Button x:Name="ConnectButton" Content="Connect"/>
                                <Button x:Name="RefreshButton" Content="Refresh" Background="#315C74" BorderBrush="#24495D"/>
                            </WrapPanel>
                            <TextBlock x:Name="StatusText" Text="Not connected" Margin="0,8,0,0" Foreground="#5B6672" TextWrapping="Wrap"/>
                        </StackPanel>
                    </GroupBox>

                    <GroupBox Header="Symbols and Data">
                        <StackPanel>
                            <TextBlock Text="Symbols"/>
                            <TextBox x:Name="SymbolsBox" Text="SPY,QQQ"/>
                            <TextBlock Text="Market data feed"/>
                            <ComboBox x:Name="FeedBox" SelectedIndex="0">
                                <ComboBoxItem Content="iex"/>
                                <ComboBoxItem Content="sip"/>
                                <ComboBoxItem Content="delayed_sip"/>
                                <ComboBoxItem Content="otc"/>
                                <ComboBoxItem Content="boats"/>
                                <ComboBoxItem Content="overnight"/>
                            </ComboBox>
                            <CheckBox x:Name="UseMarketStreamBox" Content="Stream minute bars over websocket" IsChecked="True"/>
                            <TextBlock Text="REST refresh seconds"/>
                            <TextBox x:Name="PollSecondsBox" Text="15"/>
                        </StackPanel>
                    </GroupBox>

                    <GroupBox Header="Risk Controls">
                        <StackPanel>
                            <CheckBox x:Name="DryRunBox" Content="Dry run: log orders only" IsChecked="True"/>
                            <CheckBox x:Name="MarketHoursOnlyBox" Content="Trade only while Alpaca clock is open" IsChecked="True"/>
                            <CheckBox x:Name="UseBracketBox" Content="Use bracket exits on buys" IsChecked="True"/>
                            <TextBlock Text="Max trade notional ($)"/>
                            <TextBox x:Name="MaxTradeBox" Text="100"/>
                            <TextBlock Text="Max position notional ($)"/>
                            <TextBox x:Name="MaxPositionBox" Text="500"/>
                            <TextBlock Text="Daily loss stop ($)"/>
                            <TextBox x:Name="DailyLossBox" Text="50"/>
                            <TextBlock Text="Max open positions"/>
                            <TextBox x:Name="MaxOpenPositionsBox" Text="3"/>
                        </StackPanel>
                    </GroupBox>

                    <GroupBox Header="Strategy">
                        <StackPanel>
                            <TextBlock Text="Short SMA bars"/>
                            <TextBox x:Name="ShortSmaBox" Text="9"/>
                            <TextBlock Text="Long SMA bars"/>
                            <TextBox x:Name="LongSmaBox" Text="21"/>
                            <TextBlock Text="Take profit (%)"/>
                            <TextBox x:Name="TakeProfitBox" Text="1.5"/>
                            <TextBlock Text="Stop loss (%)"/>
                            <TextBox x:Name="StopLossBox" Text="0.75"/>
                            <TextBlock Text="Cooldown minutes"/>
                            <TextBox x:Name="CooldownBox" Text="10"/>
                        </StackPanel>
                    </GroupBox>

                    <GroupBox Header="Trading">
                        <StackPanel>
                            <WrapPanel>
                                <Button x:Name="StartTradingButton" Content="Start Auto Trading" Background="#1F7A65" BorderBrush="#17624F"/>
                                <Button x:Name="StopTradingButton" Content="Stop" Background="#9F3A38" BorderBrush="#822D2B" IsEnabled="False"/>
                            </WrapPanel>
                            <Button x:Name="CancelOrdersButton" Content="Cancel Open Orders" Background="#7A4E1F" BorderBrush="#5F3C18"/>
                        </StackPanel>
                    </GroupBox>
                </StackPanel>
            </ScrollViewer>

            <Grid Grid.Column="2">
                <Grid.RowDefinitions>
                    <RowDefinition Height="118"/>
                    <RowDefinition Height="*"/>
                </Grid.RowDefinitions>

                <UniformGrid Grid.Row="0" Columns="5" Margin="0,0,0,14">
                    <Border Background="White" BorderBrush="#D6DEE6" BorderThickness="1" Padding="14" Margin="0,0,10,0">
                        <StackPanel>
                            <TextBlock Text="Equity" Foreground="#5B6672"/>
                            <TextBlock x:Name="EquityText" Text="$0.00" FontSize="22" FontWeight="SemiBold"/>
                        </StackPanel>
                    </Border>
                    <Border Background="White" BorderBrush="#D6DEE6" BorderThickness="1" Padding="14" Margin="0,0,10,0">
                        <StackPanel>
                            <TextBlock Text="Daily P/L" Foreground="#5B6672"/>
                            <TextBlock x:Name="DailyPlText" Text="$0.00" FontSize="22" FontWeight="SemiBold"/>
                        </StackPanel>
                    </Border>
                    <Border Background="White" BorderBrush="#D6DEE6" BorderThickness="1" Padding="14" Margin="0,0,10,0">
                        <StackPanel>
                            <TextBlock Text="Buying Power" Foreground="#5B6672"/>
                            <TextBlock x:Name="BuyingPowerText" Text="$0.00" FontSize="22" FontWeight="SemiBold"/>
                        </StackPanel>
                    </Border>
                    <Border Background="White" BorderBrush="#D6DEE6" BorderThickness="1" Padding="14" Margin="0,0,10,0">
                        <StackPanel>
                            <TextBlock Text="Cash" Foreground="#5B6672"/>
                            <TextBlock x:Name="CashText" Text="$0.00" FontSize="22" FontWeight="SemiBold"/>
                        </StackPanel>
                    </Border>
                    <Border Background="White" BorderBrush="#D6DEE6" BorderThickness="1" Padding="14">
                        <StackPanel>
                            <TextBlock Text="Last Refresh" Foreground="#5B6672"/>
                            <TextBlock x:Name="LastRefreshText" Text="-" FontSize="18" FontWeight="SemiBold"/>
                        </StackPanel>
                    </Border>
                </UniformGrid>

                <TabControl Grid.Row="1">
                    <TabItem Header="Strategy">
                        <DataGrid x:Name="StrategyGrid">
                            <DataGrid.Columns>
                                <DataGridTextColumn Header="Symbol" Binding="{Binding Symbol}" Width="90"/>
                                <DataGridTextColumn Header="Price" Binding="{Binding Price}" Width="110"/>
                                <DataGridTextColumn Header="Short SMA" Binding="{Binding ShortSma}" Width="120"/>
                                <DataGridTextColumn Header="Long SMA" Binding="{Binding LongSma}" Width="120"/>
                                <DataGridTextColumn Header="Bias" Binding="{Binding Bias}" Width="100"/>
                                <DataGridTextColumn Header="Bars" Binding="{Binding Bars}" Width="70"/>
                                <DataGridTextColumn Header="Last Action" Binding="{Binding LastAction}" Width="*"/>
                            </DataGrid.Columns>
                        </DataGrid>
                    </TabItem>

                    <TabItem Header="Positions">
                        <DataGrid x:Name="PositionsGrid">
                            <DataGrid.Columns>
                                <DataGridTextColumn Header="Symbol" Binding="{Binding Symbol}" Width="90"/>
                                <DataGridTextColumn Header="Side" Binding="{Binding Side}" Width="80"/>
                                <DataGridTextColumn Header="Qty" Binding="{Binding Qty}" Width="100"/>
                                <DataGridTextColumn Header="Avg Entry" Binding="{Binding AvgEntry}" Width="110"/>
                                <DataGridTextColumn Header="Cost Basis" Binding="{Binding CostBasis}" Width="120"/>
                                <DataGridTextColumn Header="Price" Binding="{Binding CurrentPrice}" Width="100"/>
                                <DataGridTextColumn Header="Market Value" Binding="{Binding MarketValue}" Width="120"/>
                                <DataGridTextColumn Header="Unrealized P/L" Binding="{Binding UnrealizedPl}" Width="120"/>
                                <DataGridTextColumn Header="Intraday P/L" Binding="{Binding IntradayPl}" Width="120"/>
                            </DataGrid.Columns>
                        </DataGrid>
                    </TabItem>

                    <TabItem Header="Open Orders">
                        <DataGrid x:Name="OrdersGrid">
                            <DataGrid.Columns>
                                <DataGridTextColumn Header="Symbol" Binding="{Binding Symbol}" Width="90"/>
                                <DataGridTextColumn Header="Side" Binding="{Binding Side}" Width="80"/>
                                <DataGridTextColumn Header="Type" Binding="{Binding Type}" Width="90"/>
                                <DataGridTextColumn Header="Qty" Binding="{Binding Qty}" Width="90"/>
                                <DataGridTextColumn Header="Status" Binding="{Binding Status}" Width="120"/>
                                <DataGridTextColumn Header="Submitted" Binding="{Binding Submitted}" Width="170"/>
                                <DataGridTextColumn Header="Client ID" Binding="{Binding ClientOrderId}" Width="*"/>
                            </DataGrid.Columns>
                        </DataGrid>
                    </TabItem>

                    <TabItem Header="Log">
                        <TextBox x:Name="LogBox" IsReadOnly="True" AcceptsReturn="True" VerticalScrollBarVisibility="Auto"
                                 HorizontalScrollBarVisibility="Auto" FontFamily="Consolas" FontSize="12"
                                 TextWrapping="NoWrap" Background="#101820" Foreground="#E6EDF3" BorderThickness="0"/>
                    </TabItem>
                </TabControl>
            </Grid>
        </Grid>
    </Grid>
</Window>
'@

$reader = New-Object System.Xml.XmlNodeReader ([xml]$xaml)
$window = [Windows.Markup.XamlReader]::Load($reader)

$ApiKeyBox = $window.FindName('ApiKeyBox')
$SecretBox = $window.FindName('SecretBox')
$RememberKeysBox = $window.FindName('RememberKeysBox')
$ConnectButton = $window.FindName('ConnectButton')
$RefreshButton = $window.FindName('RefreshButton')
$StatusText = $window.FindName('StatusText')
$SymbolsBox = $window.FindName('SymbolsBox')
$FeedBox = $window.FindName('FeedBox')
$UseMarketStreamBox = $window.FindName('UseMarketStreamBox')
$PollSecondsBox = $window.FindName('PollSecondsBox')
$DryRunBox = $window.FindName('DryRunBox')
$MarketHoursOnlyBox = $window.FindName('MarketHoursOnlyBox')
$UseBracketBox = $window.FindName('UseBracketBox')
$MaxTradeBox = $window.FindName('MaxTradeBox')
$MaxPositionBox = $window.FindName('MaxPositionBox')
$DailyLossBox = $window.FindName('DailyLossBox')
$MaxOpenPositionsBox = $window.FindName('MaxOpenPositionsBox')
$ShortSmaBox = $window.FindName('ShortSmaBox')
$LongSmaBox = $window.FindName('LongSmaBox')
$TakeProfitBox = $window.FindName('TakeProfitBox')
$StopLossBox = $window.FindName('StopLossBox')
$CooldownBox = $window.FindName('CooldownBox')
$StartTradingButton = $window.FindName('StartTradingButton')
$StopTradingButton = $window.FindName('StopTradingButton')
$CancelOrdersButton = $window.FindName('CancelOrdersButton')
$EquityText = $window.FindName('EquityText')
$DailyPlText = $window.FindName('DailyPlText')
$BuyingPowerText = $window.FindName('BuyingPowerText')
$CashText = $window.FindName('CashText')
$LastRefreshText = $window.FindName('LastRefreshText')
$StrategyGrid = $window.FindName('StrategyGrid')
$PositionsGrid = $window.FindName('PositionsGrid')
$OrdersGrid = $window.FindName('OrdersGrid')
$LogBox = $window.FindName('LogBox')

$StrategyGrid.ItemsSource = $script:StrategyRows
$PositionsGrid.ItemsSource = $script:PositionsRows
$OrdersGrid.ItemsSource = $script:OrdersRows

function Protect-AppText {
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text)) { return '' }
    ConvertTo-SecureString -String $Text -AsPlainText -Force | ConvertFrom-SecureString
}

function Unprotect-AppText {
    param([string]$ProtectedText)
    if ([string]::IsNullOrWhiteSpace($ProtectedText)) { return '' }
    $secure = ConvertTo-SecureString -String $ProtectedText
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

function Get-DecimalBoxValue {
    param($Box, [decimal]$Default)
    $culture = [System.Globalization.CultureInfo]::InvariantCulture
    $value = [decimal]0
    if ([decimal]::TryParse([string]$Box.Text, [System.Globalization.NumberStyles]::Any, $culture, [ref]$value)) {
        return $value
    }
    $Default
}

function Get-IntBoxValue {
    param($Box, [int]$Default, [int]$Minimum = 0)
    $value = 0
    if ([int]::TryParse([string]$Box.Text, [ref]$value)) {
        return [Math]::Max($Minimum, $value)
    }
    $Default
}

function Get-SelectedFeed {
    $item = $FeedBox.SelectedItem
    if ($item -and $item.PSObject.Properties['Content']) {
        return [string]$item.Content
    }
    'iex'
}

function Get-AppConfig {
    $symbols = Get-CleanSymbolList -SymbolsCsv $SymbolsBox.Text
    if ($symbols.Count -eq 0) {
        throw 'Enter at least one valid symbol.'
    }

    [PSCustomObject]@{
        Symbols = $symbols
        Feed = Get-SelectedFeed
        PollSeconds = Get-IntBoxValue -Box $PollSecondsBox -Default 15 -Minimum 5
        DryRun = [bool]$DryRunBox.IsChecked
        MarketHoursOnly = [bool]$MarketHoursOnlyBox.IsChecked
        UseBracketOrders = [bool]$UseBracketBox.IsChecked
        UseMarketStream = [bool]$UseMarketStreamBox.IsChecked
        MaxTradeNotional = Get-DecimalBoxValue -Box $MaxTradeBox -Default 100
        MaxPositionNotional = Get-DecimalBoxValue -Box $MaxPositionBox -Default 500
        DailyLossLimit = Get-DecimalBoxValue -Box $DailyLossBox -Default 50
        MaxOpenPositions = Get-IntBoxValue -Box $MaxOpenPositionsBox -Default 3 -Minimum 1
        CurrentOpenPositions = 0
        ShortPeriod = Get-IntBoxValue -Box $ShortSmaBox -Default 9 -Minimum 1
        LongPeriod = Get-IntBoxValue -Box $LongSmaBox -Default 21 -Minimum 2
        TakeProfitPercent = Get-DecimalBoxValue -Box $TakeProfitBox -Default 1.5
        StopLossPercent = Get-DecimalBoxValue -Box $StopLossBox -Default 0.75
        CooldownMinutes = Get-IntBoxValue -Box $CooldownBox -Default 10 -Minimum 0
    }
}

function Format-AppMoney {
    param($Value)
    (ConvertTo-AlpacaDecimal -Value $Value).ToString('C2')
}

function Format-AppNumber {
    param($Value, [int]$Places = 2)
    $number = ConvertTo-AlpacaDecimal -Value $Value
    $number.ToString("N$Places")
}

function Set-AppStatus {
    param([string]$Message, [string]$Color = '#5B6672')
    $StatusText.Text = $Message
    $StatusText.Foreground = [System.Windows.Media.BrushConverter]::new().ConvertFromString($Color)
}

function Add-AppLog {
    param(
        [string]$Message,
        [string]$Level = 'info'
    )

    $prefix = '[{0}] [{1}] ' -f (Get-Date -Format 'HH:mm:ss'), $Level.ToUpperInvariant()
    $LogBox.AppendText($prefix + $Message + [Environment]::NewLine)
    $LogBox.ScrollToEnd()
}

function Save-AppSettings {
    $settings = [ordered]@{
        symbols = $SymbolsBox.Text
        feed = Get-SelectedFeed
        use_market_stream = [bool]$UseMarketStreamBox.IsChecked
        poll_seconds = $PollSecondsBox.Text
        dry_run = [bool]$DryRunBox.IsChecked
        market_hours_only = [bool]$MarketHoursOnlyBox.IsChecked
        use_bracket = [bool]$UseBracketBox.IsChecked
        max_trade = $MaxTradeBox.Text
        max_position = $MaxPositionBox.Text
        daily_loss = $DailyLossBox.Text
        max_open_positions = $MaxOpenPositionsBox.Text
        short_sma = $ShortSmaBox.Text
        long_sma = $LongSmaBox.Text
        take_profit = $TakeProfitBox.Text
        stop_loss = $StopLossBox.Text
        cooldown = $CooldownBox.Text
        remember_keys = [bool]$RememberKeysBox.IsChecked
        protected_api_key = ''
        protected_secret = ''
    }

    if ($RememberKeysBox.IsChecked) {
        $settings.protected_api_key = Protect-AppText -Text $ApiKeyBox.Text
        $settings.protected_secret = Protect-AppText -Text $SecretBox.Password
    }

    $settings | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $script:SettingsPath -Encoding UTF8
}

function Load-AppSettings {
    if (-not (Test-Path -LiteralPath $script:SettingsPath)) {
        return
    }

    try {
        $settings = Get-Content -LiteralPath $script:SettingsPath -Raw | ConvertFrom-Json
        if ($settings.PSObject.Properties['symbols']) { $SymbolsBox.Text = [string]$settings.symbols }
        if ($settings.PSObject.Properties['feed']) {
            foreach ($item in $FeedBox.Items) {
                if ([string]$item.Content -eq [string]$settings.feed) { $FeedBox.SelectedItem = $item }
            }
        }
        if ($settings.PSObject.Properties['use_market_stream']) { $UseMarketStreamBox.IsChecked = [bool]$settings.use_market_stream }
        if ($settings.PSObject.Properties['poll_seconds']) { $PollSecondsBox.Text = [string]$settings.poll_seconds }
        if ($settings.PSObject.Properties['dry_run']) { $DryRunBox.IsChecked = [bool]$settings.dry_run }
        if ($settings.PSObject.Properties['market_hours_only']) { $MarketHoursOnlyBox.IsChecked = [bool]$settings.market_hours_only }
        if ($settings.PSObject.Properties['use_bracket']) { $UseBracketBox.IsChecked = [bool]$settings.use_bracket }
        if ($settings.PSObject.Properties['max_trade']) { $MaxTradeBox.Text = [string]$settings.max_trade }
        if ($settings.PSObject.Properties['max_position']) { $MaxPositionBox.Text = [string]$settings.max_position }
        if ($settings.PSObject.Properties['daily_loss']) { $DailyLossBox.Text = [string]$settings.daily_loss }
        if ($settings.PSObject.Properties['max_open_positions']) { $MaxOpenPositionsBox.Text = [string]$settings.max_open_positions }
        if ($settings.PSObject.Properties['short_sma']) { $ShortSmaBox.Text = [string]$settings.short_sma }
        if ($settings.PSObject.Properties['long_sma']) { $LongSmaBox.Text = [string]$settings.long_sma }
        if ($settings.PSObject.Properties['take_profit']) { $TakeProfitBox.Text = [string]$settings.take_profit }
        if ($settings.PSObject.Properties['stop_loss']) { $StopLossBox.Text = [string]$settings.stop_loss }
        if ($settings.PSObject.Properties['cooldown']) { $CooldownBox.Text = [string]$settings.cooldown }
        if ($settings.PSObject.Properties['remember_keys']) { $RememberKeysBox.IsChecked = [bool]$settings.remember_keys }
        if ($RememberKeysBox.IsChecked -and $settings.PSObject.Properties['protected_api_key']) { $ApiKeyBox.Text = Unprotect-AppText -ProtectedText ([string]$settings.protected_api_key) }
        if ($RememberKeysBox.IsChecked -and $settings.PSObject.Properties['protected_secret']) { $SecretBox.Password = Unprotect-AppText -ProtectedText ([string]$settings.protected_secret) }
    }
    catch {
        Add-AppLog -Level warn -Message ('Could not load saved settings: {0}' -f $_.Exception.Message)
    }
}

function Update-AccountCards {
    param($Account)

    $equity = ConvertTo-AlpacaDecimal -Value $Account.equity
    $lastEquity = ConvertTo-AlpacaDecimal -Value $Account.last_equity
    $dailyPl = $equity - $lastEquity
    $DailyPlText.Foreground = if ($dailyPl -ge 0) {
        [System.Windows.Media.BrushConverter]::new().ConvertFromString('#13795B')
    }
    else {
        [System.Windows.Media.BrushConverter]::new().ConvertFromString('#B42318')
    }

    $EquityText.Text = $equity.ToString('C2')
    $DailyPlText.Text = $dailyPl.ToString('C2')
    $BuyingPowerText.Text = Format-AppMoney $Account.buying_power
    $CashText.Text = Format-AppMoney $Account.cash
    $LastRefreshText.Text = Get-Date -Format 'h:mm:ss tt'
}

function Update-PositionsGrid {
    param($Positions)

    $script:PositionsRows.Clear()
    foreach ($position in @($Positions)) {
        $script:PositionsRows.Add([PSCustomObject]@{
            Symbol = [string]$position.symbol
            Side = [string]$position.side
            Qty = Format-AppNumber $position.qty 4
            AvgEntry = Format-AppMoney $position.avg_entry_price
            CostBasis = Format-AppMoney $position.cost_basis
            CurrentPrice = Format-AppMoney $position.current_price
            MarketValue = Format-AppMoney $position.market_value
            UnrealizedPl = Format-AppMoney $position.unrealized_pl
            IntradayPl = Format-AppMoney $position.unrealized_intraday_pl
        })
    }
}

function Update-OrdersGrid {
    param($Orders)

    $script:OrdersRows.Clear()
    foreach ($order in @($Orders)) {
        $script:OrdersRows.Add([PSCustomObject]@{
            Symbol = [string]$order.symbol
            Side = [string]$order.side
            Type = [string]$order.type
            Qty = [string]$order.qty
            Status = [string]$order.status
            Submitted = [string]$order.submitted_at
            ClientOrderId = [string]$order.client_order_id
        })
    }
}

function Update-StrategyGrid {
    param([object[]]$Snapshots)

    $script:StrategyRows.Clear()
    foreach ($snapshot in @($Snapshots)) {
        $script:StrategyRows.Add([PSCustomObject]@{
            Symbol = $snapshot.Symbol
            Price = if ($null -eq $snapshot.Price) { '-' } else { (Format-AppMoney $snapshot.Price) }
            ShortSma = if ($null -eq $snapshot.ShortSma) { '-' } else { (Format-AppMoney $snapshot.ShortSma) }
            LongSma = if ($null -eq $snapshot.LongSma) { '-' } else { (Format-AppMoney $snapshot.LongSma) }
            Bias = $snapshot.Bias
            Bars = $snapshot.Bars
            LastAction = $snapshot.LastAction
        })
    }
}

function Stop-TradingMode {
    param([string]$Reason = 'Auto trading stopped.')

    $script:TradingEnabled = $false
    $StartTradingButton.IsEnabled = $true
    $StopTradingButton.IsEnabled = $false
    Add-AppLog -Level warn -Message $Reason
    Set-AppStatus -Message $Reason -Color '#8A4B00'
}

function Refresh-Dashboard {
    param([switch]$RunStrategy)

    if ($null -eq $script:Session -or $script:IsRefreshing) {
        return
    }

    $script:IsRefreshing = $true
    try {
        $config = Get-AppConfig
        if ($config.LongPeriod -le $config.ShortPeriod) {
            throw 'Long SMA must be greater than short SMA.'
        }

        $account = Get-AlpacaAccount -Session $script:Session
        $positions = Get-AlpacaPositions -Session $script:Session
        $orders = Get-AlpacaOrders -Session $script:Session -Status open -Limit 50

        Update-AccountCards -Account $account
        Update-PositionsGrid -Positions $positions
        Update-OrdersGrid -Orders $orders

        $barsLimit = [Math]::Min(10000, [Math]::Max(1000, ($config.LongPeriod + 10) * $config.Symbols.Count))
        $bars = Get-AlpacaBars -Session $script:Session -Symbols $config.Symbols -Feed $config.Feed -Limit $barsLimit
        Add-StrategyBarsFromResponse -State $script:StrategyState -BarsResponse $bars -Symbols $config.Symbols

        $positionMap = Get-PositionMap -Positions $positions
        $openCount = @($positions | Where-Object { [Math]::Abs((ConvertTo-AlpacaDecimal -Value $_.qty)) -gt 0 }).Count
        $config.CurrentOpenPositions = $openCount

        $canTrade = [bool]$RunStrategy
        if ($canTrade -and $config.MarketHoursOnly) {
            $clock = Get-AlpacaClock -Session $script:Session
            if (-not [bool]$clock.is_open) {
                $canTrade = $false
                Set-AppStatus -Message 'Connected. Market is closed; auto trading is paused by settings.' -Color '#8A4B00'
            }
        }

        $snapshots = New-Object System.Collections.Generic.List[object]
        $stoppedByRisk = $false
        foreach ($symbol in $config.Symbols) {
            $position = if ($positionMap.ContainsKey($symbol)) { $positionMap[$symbol] } else { $null }
            if ($canTrade) {
                $decision = Invoke-StrategyDecision -State $script:StrategyState -Session $script:Session -Config $config -Symbol $symbol -Position $position -Account $account -TradingEnabled
                foreach ($event in @($decision.Events)) {
                    Add-AppLog -Level $event.Level -Message $event.Message
                }
                if ($decision.StopTrading) {
                    Stop-TradingMode -Reason 'Auto trading stopped by risk rule.'
                    $canTrade = $false
                    $stoppedByRisk = $true
                }
                $snapshots.Add($decision.Snapshot)
            }
            else {
                $snapshots.Add((Get-StrategySnapshot -State $script:StrategyState -Symbol $symbol -ShortPeriod $config.ShortPeriod -LongPeriod $config.LongPeriod))
            }
        }

        Update-StrategyGrid -Snapshots $snapshots
        if (-not $script:TradingEnabled -and -not $stoppedByRisk) {
            Set-AppStatus -Message 'Connected to Alpaca paper API.' -Color '#13795B'
        }
    }
    catch {
        Add-AppLog -Level error -Message $_.Exception.Message
        Set-AppStatus -Message $_.Exception.Message -Color '#B42318'
    }
    finally {
        $script:IsRefreshing = $false
    }
}

function Start-AppStreams {
    param([Parameter(Mandatory = $true)]$Config)

    Stop-AlpacaStreamJobs -Jobs $script:StreamJobs
    $script:StreamJobs = @()
    Set-Content -LiteralPath $script:EventLogPath -Value '' -Encoding UTF8
    $script:EventLogOffset = 0

    $tradeJob = Start-AlpacaTradeUpdateStream -ApiKey $script:Session.ApiKey -SecretKey $script:Session.SecretKey -EventLogPath $script:EventLogPath
    $script:StreamJobs += $tradeJob

    if ($Config.UseMarketStream) {
        $marketJob = Start-AlpacaMarketDataStream -ApiKey $script:Session.ApiKey -SecretKey $script:Session.SecretKey -Symbols $Config.Symbols -Feed $Config.Feed -EventLogPath $script:EventLogPath
        $script:StreamJobs += $marketJob
    }
}

function Connect-Alpaca {
    $apiKey = $ApiKeyBox.Text.Trim()
    $secret = $SecretBox.Password.Trim()
    if (-not $apiKey -or -not $secret) {
        throw 'Enter your Alpaca paper API key and secret key.'
    }

    $config = Get-AppConfig
    $script:Session = New-AlpacaSession -ApiKey $apiKey -SecretKey $secret
    Save-AppSettings

    $account = Get-AlpacaAccount -Session $script:Session
    Update-AccountCards -Account $account
    Start-AppStreams -Config $config
    Refresh-Dashboard
    Add-AppLog -Level success -Message 'Connected to Alpaca paper API and started websocket listeners.'
    Set-AppStatus -Message 'Connected to Alpaca paper API.' -Color '#13795B'
}

function Read-NewAppEvents {
    if (-not (Test-Path -LiteralPath $script:EventLogPath)) {
        return
    }

    $file = Get-Item -LiteralPath $script:EventLogPath
    if ($file.Length -lt $script:EventLogOffset) {
        $script:EventLogOffset = 0
    }

    $stream = [System.IO.File]::Open($script:EventLogPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $null = $stream.Seek($script:EventLogOffset, [System.IO.SeekOrigin]::Begin)
        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $true, 4096, $true)
        try {
            $text = $reader.ReadToEnd()
            $script:EventLogOffset = $stream.Position
        }
        finally {
            $reader.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }

    if ([string]::IsNullOrWhiteSpace($text)) {
        return
    }

    foreach ($line in ($text -split "`r?`n")) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }

        try {
            $event = $line | ConvertFrom-Json
            if ($event.source -eq 'market_data' -and $event.type -eq 'b') {
                foreach ($item in @($event.payload)) {
                    if ($item.PSObject.Properties['S'] -and $item.PSObject.Properties['c']) {
                        Add-StrategyBar -State $script:StrategyState -Symbol ([string]$item.S) -Bar ([PSCustomObject]@{ t = $item.t; c = $item.c })
                    }
                }
                continue
            }

            if ($event.type -in @('connected', 'authorization', 'listening', 'success', 'subscription')) {
                Add-AppLog -Level info -Message $event.message
            }
            elseif ($event.type -eq 'error') {
                Add-AppLog -Level error -Message $event.message
            }
            else {
                Add-AppLog -Level info -Message $event.message
                if ($event.source -eq 'trade_updates') {
                    Refresh-Dashboard
                }
            }
        }
        catch {
            Add-AppLog -Level warn -Message ('Could not process websocket event: {0}' -f $_.Exception.Message)
        }
    }
}

$pollTimer = [System.Windows.Threading.DispatcherTimer]::new()
$pollTimer.Interval = [TimeSpan]::FromSeconds(15)
$pollTimer.Add_Tick({
    try {
        if ($script:Session) {
            $config = Get-AppConfig
            $pollTimer.Interval = [TimeSpan]::FromSeconds($config.PollSeconds)
            Refresh-Dashboard -RunStrategy:($script:TradingEnabled)
        }
    }
    catch {
        Add-AppLog -Level error -Message $_.Exception.Message
    }
})
$pollTimer.Start()

$eventTimer = [System.Windows.Threading.DispatcherTimer]::new()
$eventTimer.Interval = [TimeSpan]::FromSeconds(1)
$eventTimer.Add_Tick({ Read-NewAppEvents })
$eventTimer.Start()

$ConnectButton.Add_Click({
    try {
        Connect-Alpaca
    }
    catch {
        Add-AppLog -Level error -Message $_.Exception.Message
        Set-AppStatus -Message $_.Exception.Message -Color '#B42318'
    }
})

$RefreshButton.Add_Click({ Refresh-Dashboard })

$StartTradingButton.Add_Click({
    try {
        if ($null -eq $script:Session) {
            throw 'Connect to Alpaca before starting auto trading.'
        }
        $config = Get-AppConfig
        $pollTimer.Interval = [TimeSpan]::FromSeconds($config.PollSeconds)
        $script:TradingEnabled = $true
        $StartTradingButton.IsEnabled = $false
        $StopTradingButton.IsEnabled = $true
        $mode = if ($config.DryRun) { 'dry-run' } else { 'live paper-order' }
        Add-AppLog -Level success -Message ('Auto trading started in {0} mode.' -f $mode)
        Set-AppStatus -Message ('Auto trading running in {0} mode.' -f $mode) -Color '#13795B'
        Refresh-Dashboard -RunStrategy
    }
    catch {
        Add-AppLog -Level error -Message $_.Exception.Message
        Set-AppStatus -Message $_.Exception.Message -Color '#B42318'
    }
})

$StopTradingButton.Add_Click({ Stop-TradingMode })

$CancelOrdersButton.Add_Click({
    try {
        if ($null -eq $script:Session) {
            throw 'Connect to Alpaca before canceling orders.'
        }

        $answer = [System.Windows.MessageBox]::Show('Cancel all open paper orders for this Alpaca account?', 'Cancel Open Orders', 'YesNo', 'Warning')
        if ($answer -eq 'Yes') {
            $null = Cancel-AlpacaOrders -Session $script:Session
            Add-AppLog -Level warn -Message 'Requested cancellation of all open paper orders.'
            Refresh-Dashboard
        }
    }
    catch {
        Add-AppLog -Level error -Message $_.Exception.Message
    }
})

$window.Add_Closing({
    try {
        Save-AppSettings
        Stop-AlpacaStreamJobs -Jobs $script:StreamJobs
    }
    catch {}
})

Load-AppSettings
Add-AppLog -Level info -Message 'App ready. Enter paper API credentials, connect, then start auto trading when ready.'
if ($ValidateUi) {
    'Alpaca Paper Trader UI loaded.'
    return
}
[void]$window.ShowDialog()
