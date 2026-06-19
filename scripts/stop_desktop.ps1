param(
    [switch]$RemoveVolumes
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

if ($RemoveVolumes) {
    Write-Host "Stopping Vivi and removing Docker volumes..."
    docker compose down -v
} else {
    Write-Host "Stopping Vivi..."
    docker compose down
}

Write-Host "Vivi services stopped."
