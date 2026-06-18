Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $root 'Launch Strategy Simulator Dashboard.vbs'
$wscript = Join-Path $env:WINDIR 'System32\wscript.exe'
$assets = Join-Path $root 'assets'
$icon = Join-Path $assets 'alpaca-strategy-simulator.ico'
New-Item -ItemType Directory -Force -Path $assets | Out-Null

function New-SimulatorIcon {
    param([string]$Path)

    Add-Type -AssemblyName System.Drawing

    $bitmap = [System.Drawing.Bitmap]::new(64, 64)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias

    try {
        $graphics.Clear([System.Drawing.Color]::FromArgb(15, 23, 42))
        $panelBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(14, 116, 144))
        $accentBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(236, 253, 245))
        $gridPen = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(125, 211, 252), 2)
        $linePen = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(236, 253, 245), 4)

        try {
            $graphics.FillRectangle($panelBrush, 9, 11, 46, 42)
            foreach ($x in 18, 29, 40) {
                $graphics.DrawLine($gridPen, $x, 15, $x, 49)
            }
            foreach ($y in 22, 33, 44) {
                $graphics.DrawLine($gridPen, 13, $y, 51, $y)
            }
            $points = [System.Drawing.Point[]]@(
                [System.Drawing.Point]::new(15, 42),
                [System.Drawing.Point]::new(25, 35),
                [System.Drawing.Point]::new(34, 38),
                [System.Drawing.Point]::new(48, 24)
            )
            $graphics.DrawLines($linePen, $points)
            $graphics.FillEllipse($accentBrush, 12, 39, 7, 7)
            $graphics.FillEllipse($accentBrush, 45, 21, 7, 7)
        }
        finally {
            $panelBrush.Dispose()
            $accentBrush.Dispose()
            $gridPen.Dispose()
            $linePen.Dispose()
        }

        $handle = $bitmap.GetHicon()
        $iconObject = [System.Drawing.Icon]::FromHandle($handle)
        try {
            $file = [System.IO.File]::Open($Path, [System.IO.FileMode]::Create)
            try { $iconObject.Save($file) }
            finally { $file.Dispose() }
        }
        finally {
            $iconObject.Dispose()
            Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class NativeSimulatorIcon {
    [DllImport("user32.dll", SetLastError=true)]
    public static extern bool DestroyIcon(IntPtr hIcon);
}
'@
            [NativeSimulatorIcon]::DestroyIcon($handle) | Out-Null
        }
    }
    finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

if (-not (Test-Path -LiteralPath $launcher)) {
    throw "Launcher not found: $launcher"
}

if (-not (Test-Path -LiteralPath $icon)) {
    New-SimulatorIcon -Path $icon
}

$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'Alpaca Strategy Simulator.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $wscript
$shortcut.Arguments = "`"$launcher`""
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = $icon
$shortcut.Description = 'Launch the Alpaca replay strategy simulator dashboard'
$shortcut.Save()

Write-Host "Desktop shortcut created: $shortcutPath"
