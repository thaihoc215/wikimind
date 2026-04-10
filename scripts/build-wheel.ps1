param(
    [string]$Python = "",
    [switch]$NoUpgradeBuild
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $Python) {
    if (Test-Path ".venv/Scripts/python.exe") {
        $Python = ".venv/Scripts/python.exe"
    }
    elseif (Test-Path ".venv/bin/python") {
        $Python = ".venv/bin/python"
    }
    else {
        $Python = "python"
    }
}

Write-Host "Using Python: $Python"

if (-not $NoUpgradeBuild) {
    & $Python -m pip install --upgrade build
}

& $Python -m build

Write-Host "Built artifacts in: $Root/dist"
