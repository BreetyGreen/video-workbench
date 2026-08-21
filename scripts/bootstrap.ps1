$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$existingStart = Join-Path $projectRoot 'scripts\start.ps1'

Write-Host 'Windows currently uses the existing compatibility bootstrap.'
& powershell -ExecutionPolicy Bypass -File $existingStart
if ($LASTEXITCODE -ne 0) {
    throw "Windows compatibility bootstrap failed with exit code $LASTEXITCODE"
}
