param(
    [string]$BackendUrl = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $RepoRoot ".mdns-venv"
$PythonPath = Join-Path $VenvPath "Scripts\python.exe"

if (-not (Test-Path $PythonPath)) {
    Write-Host "Creating local mDNS companion virtual environment at $VenvPath"
    python -m venv $VenvPath
}

Write-Host "Installing mDNS companion dependencies into local virtual environment"
& $PythonPath -m pip install --upgrade pip
& $PythonPath -m pip install `
    "httpx==0.28.1" `
    "pydantic==2.10.4" `
    "pydantic-settings==2.7.1" `
    "python-json-logger==3.2.1" `
    "zeroconf==0.136.2"

$env:PYTHONPATH = $RepoRoot
Push-Location $RepoRoot
try {
    if ($BackendUrl -ne "") {
        & $PythonPath -m tools.mdns_advertiser --backend-url $BackendUrl
    } else {
        & $PythonPath -m tools.mdns_advertiser
    }
} finally {
    Pop-Location
}
