$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Command
    )
    Write-Host ""
    Write-Host "==> $Name"
    & $Command
}

Push-Location $RepoRoot
try {
    Invoke-Step "Validate Docker Compose configuration" {
        docker compose config
    }

    Invoke-Step "Build backend and database services" {
        docker compose build
    }

    Invoke-Step "Start database and backend" {
        docker compose up -d db backend
    }

    Invoke-Step "Apply Alembic migrations" {
        docker compose exec -T backend alembic upgrade head
    }

    Invoke-Step "Show Alembic current revision" {
        docker compose exec -T backend alembic current
    }

    Invoke-Step "Compile application package" {
        docker compose exec -T backend python -m compileall app
    }

    Invoke-Step "Run pytest" {
        docker compose exec -T backend pytest -q
    }

    Invoke-Step "Validate /health/live" {
        Invoke-RestMethod -Uri "http://localhost:8000/health/live" -Method Get
    }

    Invoke-Step "Validate /health/ready" {
        Invoke-RestMethod -Uri "http://localhost:8000/health/ready" -Method Get
    }

    Invoke-Step "Validate /api/v1/system/info" {
        Invoke-RestMethod -Uri "http://localhost:8000/api/v1/system/info" -Method Get
    }

    Invoke-Step "Validate X-Correlation-ID response header" {
        $response = Invoke-WebRequest `
            -Uri "http://localhost:8000/health/live" `
            -Method Get `
            -UseBasicParsing
        $header = $response.Headers["X-Correlation-ID"]
        if (-not $header) {
            throw "Missing X-Correlation-ID response header."
        }
        $header
    }

    Invoke-Step "Validate stable backend instance ID across backend restart" {
        $first = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/system/info" -Method Get
        docker compose restart backend
        Start-Sleep -Seconds 8
        $second = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/system/info" -Method Get
        if ($first.instance_id -ne $second.instance_id) {
            throw "Backend instance_id changed after backend container restart."
        }
        $first.instance_id
    }

    Invoke-Step "Check whitespace in Git diff" {
        git diff --check
    }

    Invoke-Step "Show Git status" {
        git status
    }
} finally {
    Pop-Location
}
