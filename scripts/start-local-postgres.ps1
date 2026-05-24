# Start production-like Postgres on localhost:5432 (for native run_server.py).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
docker compose -f docker-compose.moonstocks.yml up -d postgres
Write-Host "Postgres on localhost:5432 — use MOONSTOCKS_DATABASE_URL from .env.native.example"
