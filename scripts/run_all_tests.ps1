# Run unit tests, optional Docker stack smoke, and local Moonstocks E2E.
param(
    [switch]$SkipDocker,
    [switch]$SkipE2e
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Find-AwsCli {
    $cmd = Get-Command aws -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $pyScripts = Join-Path $env:APPDATA "Python\Python314\Scripts\aws.cmd"
    if (Test-Path $pyScripts) { return $pyScripts }
    return $null
}

Write-Host "=== Unit tests (tests/) ===" -ForegroundColor Cyan
python -m unittest discover -s tests -p "test_*.py" -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $SkipDocker) {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        Write-Host "Docker not on PATH - skipping stack smoke (use -SkipDocker to silence)" -ForegroundColor Yellow
    } else {
        $health = $null
        try {
            $health = Invoke-WebRequest "http://127.0.0.1:3000/health" -UseBasicParsing -TimeoutSec 3
        } catch { }
        if (-not $health -or $health.StatusCode -ne 200) {
            Write-Host "Docker stack not on :3000 - start with:" -ForegroundColor Yellow
            Write-Host "  docker compose -f docker-compose.moonstocks.yml up -d"
        } else {
            Write-Host "`n=== Docker stack smoke ===" -ForegroundColor Cyan
            python scripts/test_docker_stack.py
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
    }
}

if (-not $SkipE2e) {
    Write-Host "`n=== Moonstocks E2E (mock analyzer) ===" -ForegroundColor Cyan
    python scripts/e2e_moonstocks_local.py --start-server
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$aws = Find-AwsCli
if ($aws) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $aws sts get-caller-identity 2>$null | Out-Null
    $ErrorActionPreference = $prev
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`nAWS credentials OK - deploy with scripts/deploy_moonstocks_ecr.ps1" -ForegroundColor Green
    } else {
        Write-Host "`nAWS CLI found but no credentials (aws configure or SSO)." -ForegroundColor Yellow
    }
} else {
    Write-Host "`nAWS CLI not installed - prod deploy: pip install awscli or winget install Amazon.AWSCLI" -ForegroundColor Yellow
}

Write-Host "`nAll requested checks passed." -ForegroundColor Green
