param(
    [Parameter(Mandatory = $true)]
    [string]$SourceEnv,
    [string]$TargetEnv = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($TargetEnv)) {
    $TargetEnv = Join-Path $projectRoot '.env'
}
$example = Join-Path $projectRoot '.env.example'
$sourcePath = [System.IO.Path]::GetFullPath($SourceEnv)
$targetPath = [System.IO.Path]::GetFullPath($TargetEnv)
if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
    throw 'Legacy environment file was not found.'
}
if (-not (Test-Path -LiteralPath $targetPath -PathType Leaf)) {
    Copy-Item -LiteralPath $example -Destination $targetPath
}

$allowed = @(
    'VIDEO_WORKBENCH_DIFY_BASE_URL',
    'VIDEO_WORKBENCH_DIFY_TUTORIAL_API_KEY',
    'VIDEO_WORKBENCH_DIFY_VIRAL_API_KEY',
    'VIDEO_WORKBENCH_VOLCANO_ASR_API_KEY',
    'VIDEO_WORKBENCH_VOLCANO_ASR_APP_KEY',
    'VIDEO_WORKBENCH_VOLCANO_ASR_ACCESS_KEY',
    'VIDEO_WORKBENCH_VOLCANO_TTS_API_KEY',
    'VIDEO_WORKBENCH_PEXELS_API_KEY',
    'VIDEO_WORKBENCH_PIXABAY_API_KEY',
    'VIDEO_WORKBENCH_SEEDANCE_API_KEY',
    'VIDEO_WORKBENCH_SEEDANCE_MODEL'
)

function Read-EnvMap([string]$Path) {
    $map = @{}
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $map[$matches[1]] = $matches[2]
        }
    }
    return $map
}

$source = Read-EnvMap $sourcePath
$target = Read-EnvMap $targetPath
$migrated = @()
foreach ($name in $allowed) {
    if ($source.ContainsKey($name) -and -not [string]::IsNullOrWhiteSpace($source[$name]) -and
        (-not $target.ContainsKey($name) -or [string]::IsNullOrWhiteSpace($target[$name]))) {
        $target[$name] = $source[$name]
        $migrated += $name
    }
}

$lines = foreach ($line in Get-Content -LiteralPath $targetPath -Encoding UTF8) {
    if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$' -and $target.ContainsKey($matches[1])) {
        "$($matches[1])=$($target[$matches[1]])"
    }
    else {
        $line
    }
}
$temporary = "$targetPath.tmp"
[System.IO.File]::WriteAllLines($temporary, $lines, [System.Text.UTF8Encoding]::new($false))
[System.IO.File]::Copy($temporary, $targetPath, $true)
[System.IO.File]::Delete($temporary)

[pscustomobject]@{
    MigratedCount = $migrated.Count
    MigratedNames = $migrated
    SecretValuesPrinted = $false
    SourcePreserved = $true
} | ConvertTo-Json -Depth 3
