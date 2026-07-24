param(
    [switch]$ConfirmPhase0DataLoss
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$script:InstanceIdBefore = $null
$script:DbVolumeName = $null
$script:InstanceVolumeName = $null
$script:UploadVolumeName = $null

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Command
    )
    Write-Host ""
    Write-Host "==> $Name"
    & $Command
}

function Get-ComposeContainerId {
    param([string]$Service)

    $ContainerId = docker compose ps -q $Service
    if ([string]::IsNullOrWhiteSpace($ContainerId)) {
        throw "The $Service container ID could not be determined."
    }
    return $ContainerId
}

function Get-NamedMount {
    param(
        [object]$Inspection,
        [string]$Destination
    )

    $Mount = $Inspection[0].Mounts | Where-Object { $_.Destination -eq $Destination }
    if ($null -eq $Mount) {
        throw "No mount was found for $Destination."
    }
    if ($Mount.Type -ne "volume") {
        throw "The mount at $Destination is not a Docker volume."
    }
    if ([string]::IsNullOrWhiteSpace($Mount.Name)) {
        throw "The Docker volume name for $Destination is empty."
    }
    return $Mount
}

function Assert-NonEmptyValue {
    param(
        [string]$Name,
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "$Name is empty. Refusing to continue."
    }
}

function Assert-NativeCommandSucceeded {
    param([string]$Description)

    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Wait-DatabaseHealthy {
    param([int]$TimeoutSeconds = 90)

    $StartedAt = Get-Date
    do {
        Start-Sleep -Seconds 2
        $DbContainerId = Get-ComposeContainerId "db"
        $DbHealth = docker inspect $DbContainerId |
            ConvertFrom-Json |
            ForEach-Object { $_[0].State.Health.Status }

        Write-Host "Database status:" $DbHealth

        if (((Get-Date) - $StartedAt).TotalSeconds -gt $TimeoutSeconds) {
            docker compose logs --tail 100 db
            throw "Database did not become healthy within the timeout."
        }
    }
    until ($DbHealth -eq "healthy")
}

if (-not $ConfirmPhase0DataLoss) {
    throw @"
Refusing to reset the PostgreSQL volume.

This script is for Phase 0 only and will delete the PostgreSQL data volume after
confirming that it contains no application-domain tables. Re-run with:

    .\scripts\reset-phase0-database.ps1 -ConfirmPhase0DataLoss

Do not use this after real inventory, user, upload, sync, or transaction data exists.
"@
}

Push-Location $RepoRoot
try {
    Write-Warning "PHASE 0 ONLY: this will recreate only the PostgreSQL data volume."
    Write-Warning "Instance-data and upload volumes are preserved."

    Invoke-Step "Start services for inspection" {
        docker compose up -d db backend
        Assert-NativeCommandSucceeded "docker compose up -d db backend"
        Wait-DatabaseHealthy
    }

    Invoke-Step "Record backend instance ID when available" {
        try {
            $script:InstanceIdBefore = (
                Invoke-RestMethod "http://localhost:8000/api/v1/system/info"
            ).instance_id
            Write-Host "Instance ID recorded."
        } catch {
            Write-Warning "Could not record instance ID before reset: $($_.Exception.Message)"
        }
    }

    Invoke-Step "Identify Docker volumes through inspect" {
        $DbContainerId = Get-ComposeContainerId "db"
        $DbInspection = docker inspect $DbContainerId | ConvertFrom-Json
        $DbMount = Get-NamedMount $DbInspection "/var/lib/postgresql/data"
        $script:DbVolumeName = $DbMount.Name

        $BackendContainerId = Get-ComposeContainerId "backend"
        $BackendInspection = docker inspect $BackendContainerId | ConvertFrom-Json
        $InstanceMount = Get-NamedMount $BackendInspection "/data/instance"
        $UploadMount = Get-NamedMount $BackendInspection "/data/uploads"
        $script:InstanceVolumeName = $InstanceMount.Name
        $script:UploadVolumeName = $UploadMount.Name

        Assert-NonEmptyValue "PostgreSQL volume name" $script:DbVolumeName
        Assert-NonEmptyValue "Instance-data volume name" $script:InstanceVolumeName
        Assert-NonEmptyValue "Upload volume name" $script:UploadVolumeName

        if (
            $script:DbVolumeName -eq $script:InstanceVolumeName -or
            $script:DbVolumeName -eq $script:UploadVolumeName
        ) {
            throw "The selected PostgreSQL volume overlaps with a preserved backend volume."
        }

        Write-Host "PostgreSQL data volume selected:" $script:DbVolumeName
        Write-Host "Instance-data volume preserved:" $script:InstanceVolumeName
        Write-Host "Upload volume preserved:" $script:UploadVolumeName

        $DbInspection[0].Mounts |
            Select-Object Type, Name, Source, Destination |
            Format-Table -AutoSize |
            Out-String |
            Write-Host
        $BackendInspection[0].Mounts |
            Select-Object Type, Name, Source, Destination |
            Format-Table -AutoSize |
            Out-String |
            Write-Host
    }

    Invoke-Step "Confirm Phase 0-only database schema" {
        $DbUser = docker compose exec -T db printenv POSTGRES_USER
        $DbName = docker compose exec -T db printenv POSTGRES_DB
        $Tables = docker compose exec -T db psql -U $DbUser -d $DbName -tAc `
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;"
        $TableList = @($Tables | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        $UnexpectedTables = @($TableList | Where-Object { $_ -ne "alembic_version" })

        if ($UnexpectedTables.Count -gt 0) {
            Write-Host "Tables found:"
            $TableList
            throw "Refusing to reset because application-domain tables may exist."
        }

        if ($TableList.Count -eq 0) {
            Write-Host "No public tables found."
        } else {
            Write-Host "Only Phase 0 metadata tables found:" ($TableList -join ", ")
        }
    }

    Invoke-Step "Stop Compose without deleting volumes" {
        docker compose down
        Assert-NativeCommandSucceeded "docker compose down"
    }

    Invoke-Step "Inspect selected PostgreSQL volume before removal" {
        Assert-NonEmptyValue "PostgreSQL volume name" $script:DbVolumeName
        docker volume inspect $script:DbVolumeName
        Assert-NativeCommandSucceeded "docker volume inspect PostgreSQL volume"
    }

    Invoke-Step "Remove only the selected PostgreSQL volume" {
        Assert-NonEmptyValue "PostgreSQL volume name" $script:DbVolumeName
        docker volume rm $script:DbVolumeName
        Assert-NativeCommandSucceeded "docker volume rm PostgreSQL volume"
    }

    Invoke-Step "Verify preserved volumes still exist" {
        Assert-NonEmptyValue "Instance-data volume name" $script:InstanceVolumeName
        Assert-NonEmptyValue "Upload volume name" $script:UploadVolumeName
        docker volume inspect $script:InstanceVolumeName | Out-Null
        Assert-NativeCommandSucceeded "docker volume inspect instance-data volume"
        docker volume inspect $script:UploadVolumeName | Out-Null
        Assert-NativeCommandSucceeded "docker volume inspect upload volume"
        Write-Host "Preserved volumes verified."
    }

    Invoke-Step "Start fresh PostgreSQL" {
        docker compose up -d db
        Assert-NativeCommandSucceeded "docker compose up -d db"
        Wait-DatabaseHealthy
    }

    Invoke-Step "Start backend" {
        docker compose up -d --build backend
        Assert-NativeCommandSucceeded "docker compose up -d --build backend"
    }

    Invoke-Step "Apply Alembic migrations" {
        docker compose exec -T backend alembic upgrade head
        Assert-NativeCommandSucceeded "alembic upgrade head"
        docker compose exec -T backend alembic current
        Assert-NativeCommandSucceeded "alembic current"
    }

    Invoke-Step "Verify readiness" {
        Invoke-RestMethod "http://localhost:8000/health/ready" |
            Format-List |
            Out-String |
            Write-Host
    }

    if ($null -ne $script:InstanceIdBefore) {
        Invoke-Step "Verify backend instance ID was preserved" {
            $InstanceIdAfter = (
                Invoke-RestMethod "http://localhost:8000/api/v1/system/info"
            ).instance_id
            $Preserved = $script:InstanceIdBefore -eq $InstanceIdAfter
            [PSCustomObject]@{
                Before = $script:InstanceIdBefore
                After = $InstanceIdAfter
                Preserved = $Preserved
            } | Format-List | Out-String | Write-Host
            if (-not $Preserved) {
                throw "Backend instance ID changed. Investigate preserved volume mounts."
            }
        }
    }
} finally {
    Pop-Location
}
