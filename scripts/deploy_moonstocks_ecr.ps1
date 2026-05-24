# Build and push equity-os + analyzer images to ECR (eu-north-1)
param(
    [string]$Region = "eu-north-1",
    [string]$Account = "550822830987",
    [string]$Tag = "latest"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Resolve-AwsCli {
    $cmd = Get-Command aws -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $fallback = Join-Path $env:APPDATA "Python\Python314\Scripts\aws.cmd"
    if (Test-Path $fallback) { return $fallback }
    throw "AWS CLI not found. Install: winget install Amazon.AWSCLI  OR  pip install awscli"
}

$aws = Resolve-AwsCli
& $aws sts get-caller-identity --region $Region | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "AWS credentials missing. Run: aws configure  (or SSO login) then retry."
}

$registry = "$Account.dkr.ecr.$Region.amazonaws.com"

Write-Host "Logging in to ECR..."
& $aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin $registry

$equityRepo = "$registry/equity-os-prod"
$analyzerRepo = "$registry/moonstocks-ai-analyzer-prod"

foreach ($name in @("equity-os-prod", "moonstocks-ai-analyzer-prod")) {
    & $aws ecr describe-repositories --repository-names $name --region $Region 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Creating ECR repo $name"
        & $aws ecr create-repository --repository-name $name --region $Region | Out-Null
    }
}

Write-Host "Building equity-os..."
docker build -t "${equityRepo}:${Tag}" .
docker push "${equityRepo}:${Tag}"

Write-Host "Building analyzer..."
docker build -t "${analyzerRepo}:${Tag}" ./moonstocks-ai-analyzer
docker push "${analyzerRepo}:${Tag}"

Write-Host "Done. Images:"
Write-Host "  ${equityRepo}:${Tag}"
Write-Host "  ${analyzerRepo}:${Tag}"
