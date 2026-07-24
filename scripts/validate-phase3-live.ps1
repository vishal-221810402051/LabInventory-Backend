param(
    [switch]$ConfirmLiveAi
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ApiRoot = "http://localhost:8000"
$TempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("labinventory-phase3-live-" + [guid]::NewGuid())

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

if (-not $ConfirmLiveAi) {
    throw "Live AI validation is billable. Re-run with -ConfirmLiveAi to continue."
}

Write-Warning "This script will make one billable OpenAI Responses API request."

Push-Location $RepoRoot
try {
    Invoke-Step "Start database and backend" {
        docker compose up -d --build db backend
        Assert-NativeCommandSucceeded "docker compose up -d --build db backend"
        Wait-BackendReady
    }

    Invoke-Step "Apply Alembic migrations" {
        docker compose exec -T backend alembic upgrade head
        Assert-NativeCommandSucceeded "alembic upgrade head"
    }

    Invoke-Step "Verify live AI configuration" {
        $status = Invoke-RestMethod -Uri "$ApiRoot/api/v1/ai/status" -Method Get
        if ($status.enabled -ne $true -or $status.configured -ne $true) {
            throw "AI status must be enabled and configured before live validation."
        }
        $status | Format-List | Out-String | Write-Host
    }

    Invoke-Step "Create sample photo capture" {
        $script:CaptureClientId = [guid]::NewGuid()
        $captureBody = @{
            client_capture_id = $script:CaptureClientId.ToString()
            capture_mode = "PHOTO"
            captured_at = "2026-07-25T09:00:00Z"
            manual_entry = @{
                quantity = "1.000000"
                unit = "pcs"
                category_hint = "Sensors/Modules"
                notes = "Temporary live AI validation capture"
            }
        }
        $script:Capture = Invoke-JsonPost `
            -Uri "$ApiRoot/api/v1/capture-sessions" `
            -Headers @{ "Idempotency-Key" = $script:CaptureClientId.ToString() } `
            -Body $captureBody
        "capture_id=$($script:Capture.id)" | Write-Host
    }

    Invoke-Step "Generate tiny valid JPEG test image" {
        New-Item -ItemType Directory -Path $TempDir -Force | Out-Null
        $script:PhotoPath = Join-Path $TempDir "phase3-live-sample.jpg"
        [byte[]]$bytes = 0xff, 0xd8, 0xff, 0xe0, 0x50, 0x33, 0x4a, 0x50, 0x45, 0x47
        [System.IO.File]::WriteAllBytes($script:PhotoPath, $bytes)
        $script:PhotoSha256 = (Get-FileHash -Algorithm SHA256 -Path $script:PhotoPath).Hash.ToLowerInvariant()
        $script:PhotoPath
    }

    Invoke-Step "Upload sample photo" {
        $script:ClientPhotoId = [guid]::NewGuid()
        $script:Photo = Invoke-MultipartPhotoUpload `
            -Uri "$ApiRoot/api/v1/capture-sessions/$($script:Capture.id)/photos" `
            -ClientPhotoId $script:ClientPhotoId `
            -Sha256 $script:PhotoSha256 `
            -PhotoPath $script:PhotoPath
        "photo_id=$($script:Photo.id)" | Write-Host
    }

    Invoke-Step "Upload sample OCR" {
        $script:ClientOcrId = [guid]::NewGuid()
        $ocrBody = @{
            client_ocr_id = $script:ClientOcrId.ToString()
            client_photo_id = $script:ClientPhotoId.ToString()
            engine = "ML_KIT_TEXT_RECOGNITION_V2"
            engine_version = $null
            status = "SUCCEEDED"
            processed_at = "2026-07-25T10:00:00Z"
            raw_text = "HYB11067 non-contact water level sensor"
            corrected_text = $null
            block_count = 1
            line_count = 1
            element_count = 6
            detected_language_tags = @("en")
        }
        $script:Ocr = Invoke-JsonPost `
            -Uri "$ApiRoot/api/v1/capture-sessions/$($script:Capture.id)/ocr-results" `
            -Headers @{ "Idempotency-Key" = $script:ClientOcrId.ToString() } `
            -Body $ocrBody
        "ocr_id=$($script:Ocr.id)" | Write-Host
    }

    Invoke-Step "Complete sample capture" {
        $script:Completed = Invoke-RestMethod `
            -Uri "$ApiRoot/api/v1/capture-sessions/$($script:Capture.id)/complete" `
            -Method Post
        if ($script:Completed.status -ne "READY_FOR_PROCESSING") {
            throw "Expected READY_FOR_PROCESSING, got $($script:Completed.status)."
        }
        "capture_status=$($script:Completed.status)" | Write-Host
    }

    Invoke-Step "Request live AI interpretation" {
        $script:ClientInterpretationId = [guid]::NewGuid()
        $script:InterpretationBody = @{
            client_interpretation_id = $script:ClientInterpretationId.ToString()
            requested_at = "2026-07-25T15:00:00Z"
            requested_locale = "en"
        }
        $script:Interpretation = Invoke-JsonPost `
            -Uri "$ApiRoot/api/v1/capture-sessions/$($script:Capture.id)/interpretations" `
            -Headers @{ "Idempotency-Key" = $script:ClientInterpretationId.ToString() } `
            -Body $script:InterpretationBody
        $script:Interpretation |
            Select-Object id,status,model,prompt_version,schema_version,input_token_count,output_token_count,total_token_count,latency_ms,suggestion |
            Format-List |
            Out-String |
            Write-Host
    }

    Invoke-Step "Replay live AI interpretation" {
        $replay = Invoke-JsonPost `
            -Uri "$ApiRoot/api/v1/capture-sessions/$($script:Capture.id)/interpretations" `
            -Headers @{ "Idempotency-Key" = $script:ClientInterpretationId.ToString() } `
            -Body $script:InterpretationBody
        if ($replay.id -ne $script:Interpretation.id) {
            throw "Interpretation replay returned a different server ID."
        }
        "replay_id=$($replay.id)" | Write-Host
    }
} catch {
    Write-Error "Live Phase 3 validation failed: $($_.Exception.Message)"
    throw
} finally {
    if (Test-Path $TempDir) {
        Remove-Item -LiteralPath $TempDir -Recurse -Force
    }
    Pop-Location
}
