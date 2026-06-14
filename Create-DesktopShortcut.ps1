Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $root 'Launch Alpaca Paper Trader.vbs'
$wscript = Join-Path $env:WINDIR 'System32\wscript.exe'
$assets = Join-Path $root 'assets'
$icon = Join-Path $assets 'alpaca-paper-trader.ico'
New-Item -ItemType Directory -Force -Path $assets | Out-Null

function New-AppIcon {
    param([string]$Path)

    Add-Type -AssemblyName System.Drawing

    $bitmap = [System.Drawing.Bitmap]::new(64, 64)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias

    try {
        $graphics.Clear([System.Drawing.Color]::FromArgb(23, 32, 42))
        $brush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(31, 122, 101))
        $accent = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(223, 245, 236))
        $pen = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(223, 245, 236), 5)

        try {
            $graphics.FillEllipse($brush, 8, 8, 48, 48)
            $points = [System.Drawing.Point[]]@(
                [System.Drawing.Point]::new(18, 40),
                [System.Drawing.Point]::new(28, 30),
                [System.Drawing.Point]::new(36, 34),
                [System.Drawing.Point]::new(48, 20)
            )
            $graphics.DrawLines($pen, $points)
            $graphics.FillEllipse($accent, 14, 36, 8, 8)
            $graphics.FillEllipse($accent, 44, 16, 8, 8)
        }
        finally {
            $brush.Dispose()
            $accent.Dispose()
            $pen.Dispose()
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
public static class NativeIcon {
    [DllImport("user32.dll", SetLastError=true)]
    public static extern bool DestroyIcon(IntPtr hIcon);
}
'@
            [NativeIcon]::DestroyIcon($handle) | Out-Null
        }
    }
    finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

if (-not (Test-Path -LiteralPath $icon)) {
    New-AppIcon -Path $icon
}

$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'Alpaca Paper Trader.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $wscript
$shortcut.Arguments = "`"$launcher`""
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = $icon
$shortcut.Description = 'Launch the Alpaca Paper Trader desktop app'
$shortcut.Save()

Write-Host "Desktop shortcut created: $shortcutPath"
