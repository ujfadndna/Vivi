param(
    [int]$ApiPort = 8100,
    [int]$WebPort = 5173,
    [string]$HostName = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Frontend = Join-Path $Root "frontend"

Set-Location $Root

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example"
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm is not available on PATH. Install Node.js 20+ first."
}

if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
    Push-Location $Frontend
    npm install
    Pop-Location
}

$apiCommand = "cd /d `"$Root`" && python -m uvicorn app.main:app --host $HostName --port $ApiPort --reload"
$webCommand = "cd /d `"$Frontend`" && npm run dev -- --host $HostName --port $WebPort"

Write-Host "Starting API on http://$HostName`:$ApiPort"
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", $apiCommand -WindowStyle Hidden

Write-Host "Starting Web on http://$HostName`:$WebPort/chat"
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", $webCommand -WindowStyle Hidden

Write-Host ""
Write-Host "Her Web app: http://localhost:$WebPort/chat"
Write-Host "API health:  http://localhost:$ApiPort/health"
