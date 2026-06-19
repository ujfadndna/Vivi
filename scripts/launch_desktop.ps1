param(
    [switch]$Build,
    [switch]$NoOpen,
    [int]$TimeoutSeconds = 180,
    [string]$Url = "http://localhost:5173/chat"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message"
}

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Open-ViviWindow([string]$TargetUrl) {
    $edge = Get-Command "msedge.exe" -ErrorAction SilentlyContinue
    if ($edge) {
        Start-Process $edge.Source -ArgumentList "--app=$TargetUrl"
        return
    }

    $chrome = Get-Command "chrome.exe" -ErrorAction SilentlyContinue
    if ($chrome) {
        Start-Process $chrome.Source -ArgumentList "--app=$TargetUrl"
        return
    }

    Start-Process $TargetUrl
}

if (-not (Test-Command "docker")) {
    throw "Docker is not available on PATH. Install and start Docker Desktop first."
}

try {
    docker compose version | Out-Null
} catch {
    throw "Docker Compose v2 is not available. Update Docker Desktop and try again."
}

try {
    docker info | Out-Null
} catch {
    throw "Docker Desktop is not running. Start Docker Desktop, wait until it is ready, then open Vivi again."
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example"
}

# Desktop mode is intentionally mock-first. Docker Compose reads .env by
# default, so set process env vars to keep old local-model .env files from
# making the lightweight desktop package import heavy model dependencies.
$env:WORKSPACE_DIR = "./workspace"
$env:API_PORT = "8100"
$env:WEB_ORIGIN = "http://localhost:5173"
$env:DEPLOYMENT_MODE = "mock"
$env:INGEST_BACKEND = "mock"
$env:TTS_BACKEND = "mock"
$env:INDEXTTS_API_URL = ""
$env:MUSETALK_BACKEND = "mock"
$env:SEGMENT_BACKEND = "mock"
$env:BACKGROUND_BACKEND = "mock"
$env:COMPOSITE_BACKEND = "local"
$env:SKIP_RVM = "true"
$env:CELERY_TASK_ALWAYS_EAGER = "true"
$env:CELERY_BROKER_URL = "redis://redis:6379/0"
$env:CELERY_RESULT_BACKEND = "redis://redis:6379/1"

$apiImage = docker image ls her-api --format "{{.Repository}}:{{.Tag}}"
$webImage = docker image ls her-web --format "{{.Repository}}:{{.Tag}}"
if ($Build -or -not $apiImage -or -not $webImage) {
    Write-Step "Building Vivi Docker images"
    docker compose build
}

Write-Step "Starting Vivi services"
docker compose up -d

Write-Step "Waiting for Vivi API"
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$health = $null
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-RestMethod -Method Get -Uri "http://localhost:5173/health" -TimeoutSec 5
        if ($health.status -eq "ok") {
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $health -or $health.status -ne "ok") {
    docker compose ps
    docker compose logs api --tail 80
    throw "Vivi API did not become ready within $TimeoutSeconds seconds."
}

Write-Host ""
Write-Host "Vivi is ready."
Write-Host "Mode: $($health.profile.deployment_mode)"
Write-Host "Chat: $Url"
Write-Host "Health: http://localhost:5173/health"

if (-not $NoOpen) {
    Open-ViviWindow $Url
}
