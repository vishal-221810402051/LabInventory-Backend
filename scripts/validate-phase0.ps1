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

function Assert-NativeCommandSucceeded {
    param([string]$Description)

    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Show-ReadinessDiagnostics {
    Write-Host ""
    Write-Host "Readiness diagnostics:"

    try {
        Write-Host "Sanitized backend DATABASE_URL:"
        docker compose exec -T backend python -c "import os; from sqlalchemy.engine import make_url; print(make_url(os.environ['DATABASE_URL']).render_as_string(hide_password=True))"
    } catch {
        Write-Warning "Could not read sanitized backend DATABASE_URL: $($_.Exception.Message)"
    }

    try {
        Write-Host "Backend DATABASE_URL password hash:"
        docker compose exec -T backend python -c "import os, hashlib; from sqlalchemy.engine import make_url; password = make_url(os.environ['DATABASE_URL']).password or ''; print(hashlib.sha256(password.encode()).hexdigest())"
        Write-Host "DB POSTGRES_PASSWORD hash:"
        docker compose exec -T db sh -lc 'printf "%s" "$POSTGRES_PASSWORD" | sha256sum'
    } catch {
        Write-Warning "Could not compare password hashes: $($_.Exception.Message)"
    }

    try {
        Write-Host "Recent PostgreSQL authentication messages:"
        docker compose logs --tail 100 db |
            Select-String -Pattern "password authentication failed|Skipping initialization"
    } catch {
        Write-Warning "Could not inspect database logs: $($_.Exception.Message)"
    }

    Write-Host ""
    Write-Host "If hashes match but PostgreSQL logs show password authentication failures"
    Write-Host "and startup logs say initialization was skipped, the Phase 0 PostgreSQL"
    Write-Host "volume likely has a stale role password. After confirming there is no"
    Write-Host "real inventory/user data, run:"
    Write-Host ".\scripts\reset-phase0-database.ps1 -ConfirmPhase0DataLoss"
}

function Invoke-ReadinessCheck {
    try {
        Invoke-RestMethod -Uri "http://localhost:8000/health/ready" -Method Get
    } catch {
        Write-Warning "/health/ready failed."
        if ($_.ErrorDetails.Message) {
            Write-Host "Response body:"
            Write-Host $_.ErrorDetails.Message
        }
        Show-ReadinessDiagnostics
        throw
    }
}

Push-Location $RepoRoot
try {
    Invoke-Step "Validate Docker Compose configuration" {
        docker compose config
        Assert-NativeCommandSucceeded "docker compose config"
    }

    Invoke-Step "Build backend and database services" {
        docker compose build
        Assert-NativeCommandSucceeded "docker compose build"
    }

    Invoke-Step "Start database and backend" {
        docker compose up -d db backend
        Assert-NativeCommandSucceeded "docker compose up -d db backend"
    }

    Invoke-Step "Apply Alembic migrations" {
        docker compose exec -T backend alembic upgrade head
        Assert-NativeCommandSucceeded "alembic upgrade head"
    }

    Invoke-Step "Show Alembic current revision" {
        docker compose exec -T backend alembic current
        Assert-NativeCommandSucceeded "alembic current"
    }

    Invoke-Step "Compile application package" {
        docker compose exec -T backend python -m compileall app
        Assert-NativeCommandSucceeded "compileall app"
    }

    Invoke-Step "Run pytest" {
        docker compose exec -T backend pytest -q
        Assert-NativeCommandSucceeded "pytest"
    }

    Invoke-Step "Validate /health/live" {
        Invoke-RestMethod -Uri "http://localhost:8000/health/live" -Method Get |
            Format-List |
            Out-String |
            Write-Host
    }

    Invoke-Step "Validate /health/ready" {
        Invoke-ReadinessCheck |
            Format-List |
            Out-String |
            Write-Host
    }

    Invoke-Step "Validate /api/v1/system/info" {
        Invoke-RestMethod -Uri "http://localhost:8000/api/v1/system/info" -Method Get |
            Format-List |
            Out-String |
            Write-Host
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
        Assert-NativeCommandSucceeded "docker compose restart backend"
        Start-Sleep -Seconds 8
        $second = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/system/info" -Method Get
        if ($first.instance_id -ne $second.instance_id) {
            throw "Backend instance_id changed after backend container restart."
        }
        $first.instance_id
    }

    Invoke-Step "Check whitespace in Git diff" {
        git diff --check
        Assert-NativeCommandSucceeded "git diff --check"
    }

    Invoke-Step "Show Git status" {
        git status
    }
} finally {
    Pop-Location
}
