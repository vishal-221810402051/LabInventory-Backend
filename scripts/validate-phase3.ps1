$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ApiRoot = "http://localhost:8000"
$PreviousEnv = @{}
$TempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("labinventory-phase3-" + [guid]::NewGuid())

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

function Set-ProcessEnv {
    param(
        [string]$Name,
        [string]$Value
    )

    if (-not $script:PreviousEnv.ContainsKey($Name)) {
        $script:PreviousEnv[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
    }
    [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
}

function Restore-ProcessEnv {
    foreach ($name in $script:PreviousEnv.Keys) {
        [Environment]::SetEnvironmentVariable($name, $script:PreviousEnv[$name], "Process")
    }
}

function Invoke-JsonPost {
    param(
        [string]$Uri,
        [object]$Body,
        [hashtable]$Headers = @{}
    )

    Invoke-RestMethod `
        -Uri $Uri `
        -Method Post `
        -ContentType "application/json" `
        -Headers $Headers `
        -Body ($Body | ConvertTo-Json -Depth 8)
}

function Wait-BackendReady {
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        try {
            Invoke-RestMethod -Uri "$ApiRoot/health/live" -Method Get -TimeoutSec 3 | Out-Null
            return
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    throw "Backend did not become ready in time."
}

function Invoke-ExpectedError {
    param(
        [string]$Uri,
        [object]$Body,
        [hashtable]$Headers,
        [string]$ExpectedCode
    )

    try {
        Invoke-JsonPost -Uri $Uri -Body $Body -Headers $Headers | Out-Null
        throw "Expected $ExpectedCode, but request succeeded."
    } catch {
        if (-not $_.ErrorDetails.Message) {
            throw
        }
        $errorBody = $_.ErrorDetails.Message | ConvertFrom-Json
        if ($errorBody.error.code -ne $ExpectedCode) {
            throw "Expected $ExpectedCode, got $($errorBody.error.code)."
        }
        $errorBody
    }
}

function New-InterpretationPayload {
    param([guid]$ClientInterpretationId)

    @{
        client_interpretation_id = $ClientInterpretationId.ToString()
        requested_at = "2026-07-25T15:00:00Z"
        requested_locale = "en"
    }
}

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Path $TempDir -Force | Out-Null
    $script:NoKeyComposeOverride = Join-Path $TempDir "compose-no-openai-key.yml"
    @"
services:
  backend:
    environment:
      OPENAI_API_KEY: ""
"@ | Set-Content -LiteralPath $script:NoKeyComposeOverride -Encoding ASCII

    Set-ProcessEnv -Name "AI_INTERPRETATION_ENABLED" -Value "false"
    Set-ProcessEnv -Name "OPENAI_MODEL" -Value "gpt-5-mini"
    Set-ProcessEnv -Name "OPENAI_STORE" -Value "false"

    Invoke-Step "Validate Docker Compose configuration" {
        docker compose config
        Assert-NativeCommandSucceeded "docker compose config"
    }

    Invoke-Step "Start database and backend with AI disabled" {
        docker compose up -d --build db backend
        Assert-NativeCommandSucceeded "docker compose up -d --build db backend"
        Wait-BackendReady
    }

    Invoke-Step "Apply Alembic migrations" {
        docker compose exec -T backend alembic upgrade head
        Assert-NativeCommandSucceeded "alembic upgrade head"
    }

    Invoke-Step "Verify Alembic current and one head" {
        docker compose exec -T backend alembic current
        Assert-NativeCommandSucceeded "alembic current"
        $heads = docker compose exec -T backend alembic heads
        Assert-NativeCommandSucceeded "alembic heads"
        $headCount = @($heads | Where-Object { $_.Trim() }).Count
        if ($headCount -ne 1) {
            throw "Expected one Alembic head, found $headCount."
        }
        $heads
    }

    Invoke-Step "Compile app, tests, and tools" {
        docker compose exec -T backend python -m compileall app tests tools
        Assert-NativeCommandSucceeded "compileall"
    }

    Invoke-Step "Run pytest" {
        docker compose exec -T backend pytest -q
        Assert-NativeCommandSucceeded "pytest"
    }

    Invoke-Step "Run Ruff" {
        docker compose exec -T backend ruff check .
        Assert-NativeCommandSucceeded "ruff"
    }

    Invoke-Step "Run Mypy" {
        docker compose exec -T backend mypy app tools
        Assert-NativeCommandSucceeded "mypy"
    }

    Invoke-Step "Verify Phase 0 endpoints" {
        Invoke-RestMethod -Uri "$ApiRoot/health/live" -Method Get | Format-List | Out-String | Write-Host
        Invoke-RestMethod -Uri "$ApiRoot/health/ready" -Method Get | Format-List | Out-String | Write-Host
        Invoke-RestMethod -Uri "$ApiRoot/api/v1/system/info" -Method Get | Format-List | Out-String | Write-Host
    }

    Invoke-Step "Verify AI status endpoint disabled" {
        $status = Invoke-RestMethod -Uri "$ApiRoot/api/v1/ai/status" -Method Get
        if ($status.enabled -ne $false -or $status.configured -ne $false) {
            throw "Expected disabled and unconfigured AI status."
        }
        if ($status.image_input_enabled -ne $false) {
            throw "Expected image_input_enabled=false."
        }
        $status | Format-List | Out-String | Write-Host
    }

    Invoke-Step "Verify disabled behavior safely" {
        $clientInterpretationId = [guid]::NewGuid()
        $payload = New-InterpretationPayload -ClientInterpretationId $clientInterpretationId
        Invoke-ExpectedError `
            -Uri "$ApiRoot/api/v1/capture-sessions/$([guid]::NewGuid())/interpretations" `
            -Headers @{ "Idempotency-Key" = $clientInterpretationId.ToString() } `
            -Body $payload `
            -ExpectedCode "AI_INTERPRETATION_DISABLED" |
            Format-List |
            Out-String |
            Write-Host
    }

    Invoke-Step "Restart backend with AI enabled but no key" {
        Set-ProcessEnv -Name "AI_INTERPRETATION_ENABLED" -Value "true"
        docker compose -f docker-compose.yml -f $script:NoKeyComposeOverride up -d --build backend
        Assert-NativeCommandSucceeded "docker compose override up -d --build backend"
        Wait-BackendReady
    }

    Invoke-Step "Verify unconfigured behavior safely" {
        $status = Invoke-RestMethod -Uri "$ApiRoot/api/v1/ai/status" -Method Get
        if ($status.enabled -ne $true -or $status.configured -ne $false) {
            throw "Expected enabled and unconfigured AI status."
        }
        $clientInterpretationId = [guid]::NewGuid()
        $payload = New-InterpretationPayload -ClientInterpretationId $clientInterpretationId
        Invoke-ExpectedError `
            -Uri "$ApiRoot/api/v1/capture-sessions/$([guid]::NewGuid())/interpretations" `
            -Headers @{ "Idempotency-Key" = $clientInterpretationId.ToString() } `
            -Body $payload `
            -ExpectedCode "AI_PROVIDER_NOT_CONFIGURED" |
            Format-List |
            Out-String |
            Write-Host
    }

    Invoke-Step "Return backend to AI disabled mode" {
        Set-ProcessEnv -Name "AI_INTERPRETATION_ENABLED" -Value "false"
        docker compose up -d --build backend
        Assert-NativeCommandSucceeded "docker compose up -d --build backend"
        Wait-BackendReady
    }

    Invoke-Step "Validate OpenAPI endpoints" {
        Invoke-RestMethod -Uri "$ApiRoot/openapi.json" -Method Get | Out-Null
        Invoke-WebRequest -Uri "$ApiRoot/docs" -Method Get -UseBasicParsing | Out-Null
        Invoke-WebRequest -Uri "$ApiRoot/redoc" -Method Get -UseBasicParsing | Out-Null
        Write-Host "OpenAPI, Swagger UI, and ReDoc returned successfully."
    }

    Invoke-Step "Check whitespace in Git diff" {
        git diff --check
        Assert-NativeCommandSucceeded "git diff --check"
    }

    Invoke-Step "Show Git status" {
        git status
    }
} catch {
    Write-Error "Phase 3 validation failed: $($_.Exception.Message)"
    throw
} finally {
    if (Test-Path $TempDir) {
        Remove-Item -LiteralPath $TempDir -Recurse -Force
    }
    Restore-ProcessEnv
    Pop-Location
}
