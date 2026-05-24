# Install repo-bundled agent skills and MCP template into Cursor user config.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$AgentSkills = Join-Path $Root "agent\skills"
$CursorSkills = Join-Path $env:USERPROFILE ".cursor\skills"
$McpExample = Join-Path $Root "agent\mcp\mcp.json.example"
$McpTarget = Join-Path $env:USERPROFILE ".cursor\mcp.json"

if (-not (Test-Path $AgentSkills)) {
    throw "Missing $AgentSkills — run from a full companyData clone."
}

New-Item -ItemType Directory -Force -Path $CursorSkills | Out-Null

Get-ChildItem $AgentSkills -Directory | ForEach-Object {
    $dest = Join-Path $CursorSkills $_.Name
    Write-Host "Installing skill: $($_.Name) -> $dest"
    if (Test-Path $dest) {
        $backup = "$dest.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Write-Host "  Backing up existing to $backup"
        Move-Item $dest $backup
    }
    Copy-Item -Recurse $_.FullName $dest
}

if (Test-Path $McpTarget) {
    Write-Host ""
    Write-Host "MCP config already exists: $McpTarget"
    Write-Host "Merge eodhd server from: $McpExample"
    Write-Host "  (do not overwrite if you already have other MCP servers)"
} else {
    Copy-Item $McpExample $McpTarget
    Write-Host "Created $McpTarget from example — set YOUR_EODHD_API_KEY"
}

Write-Host ""
Write-Host "Done. Restart Cursor. See agent/README.md"
