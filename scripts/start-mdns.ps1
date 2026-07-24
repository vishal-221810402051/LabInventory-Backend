param(
    [string]$BackendUrl = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $RepoRoot ".mdns-venv"
$VenvPython = Join-Path $RepoRoot ".mdns-venv\Scripts\python.exe"

function Assert-NativeCommandSucceeded {
    param([string]$Description)

    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating local mDNS companion virtual environment at $VenvPath"
    python -m venv $VenvPath
    Assert-NativeCommandSucceeded "python -m venv"
}

Write-Host "Using mDNS Python: $VenvPython"
Write-Host "Installing mDNS companion dependencies into local virtual environment"
& $VenvPython -m pip install --upgrade pip
Assert-NativeCommandSucceeded "pip install --upgrade pip"
& $VenvPython -m pip install `
    "httpx==0.28.1" `
    "pydantic==2.10.4" `
    "pydantic-settings==2.7.1" `
    "python-json-logger==3.2.1" `
    "zeroconf==0.136.2"
Assert-NativeCommandSucceeded "pip install mDNS companion dependencies"

$env:PYTHONPATH = $RepoRoot
Push-Location $RepoRoot
try {
    if ($BackendUrl -ne "") {
        & $VenvPython -m tools.mdns_advertiser --backend-url $BackendUrl
    } else {
        & $VenvPython -m tools.mdns_advertiser
    }
    Assert-NativeCommandSucceeded "mDNS advertiser"
} finally {
    Pop-Location
}
