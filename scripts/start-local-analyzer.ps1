# Analyzer for native equity-os (run_server.py on :3000, Postgres in Docker).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location (Join-Path $Root "moonstocks-ai-analyzer")

$env:ANALYSIS_API_BASE_URL = "http://127.0.0.1:3000"
if (-not $env:ANALYZER_LLM_PROVIDER) { $env:ANALYZER_LLM_PROVIDER = "openai" }

Write-Host "Starting analyzer on http://127.0.0.1:8000 -> equity-os http://127.0.0.1:3000"
python -m uvicorn main:app --host 0.0.0.0 --port 8000
