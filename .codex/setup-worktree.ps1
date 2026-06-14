[CmdletBinding()]
param(
    [switch]$SmokeOnly
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $RepoRoot

$VenvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$RuntimeLocalAppData = Join-Path $RepoRoot '.runtime\localappdata'

New-Item -ItemType Directory -Force -Path $RuntimeLocalAppData | Out-Null
$env:LOCALAPPDATA = $RuntimeLocalAppData
$env:ALPACA_TRADER_PORT = '0'

if (-not (Test-Path $VenvPython)) {
    if ($SmokeOnly) {
        throw 'Virtual environment is missing. Run .\.codex\setup-worktree.ps1 first.'
    }

    $Python = (Get-Command python -ErrorAction SilentlyContinue)
    if (-not $Python) {
        $Python = (Get-Command py -ErrorAction SilentlyContinue)
    }
    if (-not $Python) {
        throw 'Python was not found on PATH.'
    }

    & $Python.Source -m venv .venv
}

if (-not $SmokeOnly) {
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r requirements.txt
    & $VenvPython -m compileall -q python_app
}

& $VenvPython python_app\run.py --smoke
