# Repair hung Docker Desktop Linux engine (500 on dockerDesktopLinuxEngine).
# Run from PowerShell (no admin usually required). Takes ~30-90s when healthy.
param(
    [switch]$SkipCompose,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$DockerExe = "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe"
$docker = "${env:ProgramFiles}\Docker\Docker\resources\bin\docker.exe"
if (-not (Test-Path $docker)) { $docker = "docker" }
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Log = Join-Path $env:TEMP "repair-docker-engine.log"

function Log($msg) {
    $line = "$(Get-Date -Format 'HH:mm:ss') $msg"
    $line | Out-File $Log -Append
    if (-not $Quiet) { Write-Host $line }
}

Log "=== repair-docker-engine ==="

Log "Stopping docker-desktop WSL distros..."
wsl -t docker-desktop 2>$null | Out-Null
wsl -t docker-desktop-data 2>$null | Out-Null
Start-Sleep 2
Log "WSL shutdown..."
wsl --shutdown 2>$null | Out-Null
Start-Sleep 3

Log "Stopping Docker Desktop processes..."
Get-Process "Docker Desktop", "com.docker.backend", "com.docker.build" -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep 4

if (Test-Path $DockerExe) {
    Log "Starting Docker Desktop..."
    Start-Process $DockerExe
} else {
    Log "ERROR: Docker Desktop not found at $DockerExe"
    exit 1
}

$ready = $false
$sw = [Diagnostics.Stopwatch]::StartNew()
for ($i = 0; $i -lt 36; $i++) {
    Start-Sleep 5
    & $docker info 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $ready = $true
        Log "Engine READY in $([math]::Round($sw.Elapsed.TotalSeconds))s"
        break
    }
    if ($i % 4 -eq 0) { Log "  waiting... $([math]::Round($sw.Elapsed.TotalSeconds))s" }
}

if (-not $ready) {
    Log "ERROR: Engine not ready after $([math]::Round($sw.Elapsed.TotalSeconds))s"
    Log "Try: Docker Desktop -> Troubleshoot -> Restart Docker Desktop"
    Log "Or: Docker Desktop -> Troubleshoot -> Clean / Purge data (last resort)"
    exit 1
}

& $docker version --format "Server: {{.Server.Version}}" 2>$null | ForEach-Object { Log $_ }

if (-not $SkipCompose) {
    Set-Location $Root
    Log "Starting Postgres (compose)..."
    & $docker compose -f docker-compose.moonstocks.yml up -d postgres 2>&1 | ForEach-Object { Log $_ }
    if ($LASTEXITCODE -eq 0) {
        Log "Postgres on localhost:5432"
    }
}

Log "Done. Log: $Log"
exit 0
