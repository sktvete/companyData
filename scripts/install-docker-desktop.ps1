# Install Docker Desktop on Windows (requires admin; reboot may be needed)
# Usage: powershell -ExecutionPolicy Bypass -File scripts/install-docker-desktop.ps1

$ErrorActionPreference = "Stop"

if (Get-Command docker -ErrorAction SilentlyContinue) {
    Write-Host "Docker CLI already available: $(docker --version)"
    exit 0
}

Write-Host "Installing Docker Desktop via winget..."
winget install -e --id Docker.DockerDesktop `
    --accept-package-agreements `
    --accept-source-agreements

Write-Host @"

Docker Desktop installed (or already present).

1. Start 'Docker Desktop' from the Start menu.
2. Wait until the whale icon shows 'Engine running'.
3. Verify: docker version
4. Run stack: docker compose -f docker-compose.moonstocks.yml up --build

If WSL2 is required, follow the prompt in Docker Desktop settings.
"@
