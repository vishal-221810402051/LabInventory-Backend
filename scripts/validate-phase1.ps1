$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ApiRoot = "http://localhost:8000"
$TempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("labinventory-phase1-" + [guid]::NewGuid())

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

function Invoke-JsonPost {
    param(
        [string]$Uri,
        [object]$Body,
        [hashtable]$Headers = @{}
    )

    $json = $Body | ConvertTo-Json -Depth 6
    Invoke-RestMethod `
        -Uri $Uri `
        -Method Post `
        -ContentType "application/json" `
        -Headers $Headers `
        -Body $json
}

function Invoke-MultipartPhotoUpload {
    param(
        [string]$Uri,
        [guid]$ClientPhotoId,
        [string]$Sha256,
        [string]$PhotoPath
    )

    Add-Type -AssemblyName System.Net.Http
    $client = [System.Net.Http.HttpClient]::new()
    $fileStream = [System.IO.File]::OpenRead($PhotoPath)
    $multipart = [System.Net.Http.MultipartFormDataContent]::new()
    try {
        $multipart.Add([System.Net.Http.StringContent]::new($ClientPhotoId.ToString()), "client_photo_id")
        $multipart.Add([System.Net.Http.StringContent]::new($Sha256), "sha256")
        $fileContent = [System.Net.Http.StreamContent]::new($fileStream)
        $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("image/jpeg")
        $multipart.Add($fileContent, "file", "sample.jpg")

        $request = [System.Net.Http.HttpRequestMessage]::new(
            [System.Net.Http.HttpMethod]::Post,
            $Uri
        )
        $request.Headers.Add("Idempotency-Key", $ClientPhotoId.ToString())
        $request.Content = $multipart

        $response = $client.SendAsync($request).GetAwaiter().GetResult()
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            throw "Photo upload failed with status $([int]$response.StatusCode): $body"
        }
        $body | ConvertFrom-Json
    } finally {
        $multipart.Dispose()
        $fileStream.Dispose()
        $client.Dispose()
    }
}

Push-Location $RepoRoot
try {
    Invoke-Step "Validate Docker Compose configuration" {
        docker compose config
        Assert-NativeCommandSucceeded "docker compose config"
    }

    Invoke-Step "Start database and backend" {
        docker compose up -d --build db backend
        Assert-NativeCommandSucceeded "docker compose up -d --build db backend"
    }

    Invoke-Step "Apply Alembic migrations" {
        docker compose exec -T backend alembic upgrade head
        Assert-NativeCommandSucceeded "alembic upgrade head"
    }

    Invoke-Step "Show Alembic current revision" {
        docker compose exec -T backend alembic current
        Assert-NativeCommandSucceeded "alembic current"
    }

    Invoke-Step "Verify one Alembic head" {
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

    Invoke-Step "Validate Phase 0 health endpoints" {
        Invoke-RestMethod -Uri "$ApiRoot/health/live" -Method Get | Format-List | Out-String | Write-Host
        Invoke-RestMethod -Uri "$ApiRoot/health/ready" -Method Get | Format-List | Out-String | Write-Host
        Invoke-RestMethod -Uri "$ApiRoot/api/v1/system/info" -Method Get | Format-List | Out-String | Write-Host
    }

    Invoke-Step "Create sample capture session" {
        $script:CaptureClientId = [guid]::NewGuid()
        $captureBody = @{
            client_capture_id = $script:CaptureClientId.ToString()
            capture_mode = "PHOTO"
            captured_at = "2026-07-24T18:30:00Z"
            manual_entry = @{
                name = "Phase 1 validation sample"
                quantity = "1.000000"
                unit = "pcs"
                category_hint = "Validation"
                notes = "Temporary validation capture"
            }
        }
        $script:Capture = Invoke-JsonPost `
            -Uri "$ApiRoot/api/v1/capture-sessions" `
            -Headers @{ "Idempotency-Key" = $script:CaptureClientId.ToString() } `
            -Body $captureBody
        $script:Capture | Format-List | Out-String | Write-Host
    }

    Invoke-Step "Generate tiny valid JPEG test image" {
        New-Item -ItemType Directory -Path $TempDir -Force | Out-Null
        $script:PhotoPath = Join-Path $TempDir "phase1-sample.jpg"
        [byte[]]$bytes = 0xff, 0xd8, 0xff, 0xe0, 0x50, 0x31, 0x4a, 0x50, 0x45, 0x47
        [System.IO.File]::WriteAllBytes($script:PhotoPath, $bytes)
        $script:PhotoSha256 = (Get-FileHash -Algorithm SHA256 -Path $script:PhotoPath).Hash.ToLowerInvariant()
        $script:PhotoPath
    }

    Invoke-Step "Upload sample capture photo" {
        $script:ClientPhotoId = [guid]::NewGuid()
        $script:Photo = Invoke-MultipartPhotoUpload `
            -Uri "$ApiRoot/api/v1/capture-sessions/$($script:Capture.id)/photos" `
            -ClientPhotoId $script:ClientPhotoId `
            -Sha256 $script:PhotoSha256 `
            -PhotoPath $script:PhotoPath
        $script:Photo | Format-List | Out-String | Write-Host
    }

    Invoke-Step "Complete sample capture" {
        $script:Completed = Invoke-RestMethod `
            -Uri "$ApiRoot/api/v1/capture-sessions/$($script:Capture.id)/complete" `
            -Method Post
        if ($script:Completed.status -ne "READY_FOR_PROCESSING") {
            throw "Expected READY_FOR_PROCESSING, got $($script:Completed.status)."
        }
        $script:Completed | Format-List | Out-String | Write-Host
    }

    Invoke-Step "Fetch completed sample capture" {
        Invoke-RestMethod `
            -Uri "$ApiRoot/api/v1/capture-sessions/$($script:Capture.id)" `
            -Method Get |
            Format-List |
            Out-String |
            Write-Host
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
    Write-Error "Phase 1 validation failed: $($_.Exception.Message)"
    throw
} finally {
    if (Test-Path $TempDir) {
        Remove-Item -LiteralPath $TempDir -Recurse -Force
    }
    Pop-Location
}
