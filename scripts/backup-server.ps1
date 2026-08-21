param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$Destination = ''
)

$ErrorActionPreference = 'Stop'

$resolvedProject = [System.IO.Path]::GetFullPath($ProjectRoot)
if ([string]::IsNullOrWhiteSpace($Destination)) {
    $Destination = Join-Path $resolvedProject 'backups'
}
$resolvedDestination = [System.IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Path $resolvedDestination -Force | Out-Null

$dataPath = Join-Path $resolvedProject 'data\control-plane'
if (-not (Test-Path -LiteralPath $dataPath -PathType Container)) {
    throw "Control-plane data directory not found: $dataPath"
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$archive = Join-Path $resolvedDestination "video-workbench-$stamp.zip"
Compress-Archive -LiteralPath $dataPath -DestinationPath $archive -CompressionLevel Optimal
if (-not (Test-Path -LiteralPath $archive -PathType Leaf) -or (Get-Item -LiteralPath $archive).Length -eq 0) {
    throw 'Backup archive verification failed.'
}

[pscustomobject]@{ Archive = $archive; SizeBytes = (Get-Item -LiteralPath $archive).Length; CreatedAt = (Get-Date).ToString('o') } | ConvertTo-Json
