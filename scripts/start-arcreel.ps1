$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$deployDir = Join-Path $projectRoot 'deploy\arcreel'
$composePath = Join-Path $deployDir 'compose.yml'
$envPath = Join-Path $deployDir '.env'
$envExamplePath = Join-Path $deployDir '.env.example'

if (-not (Test-Path -LiteralPath $composePath -PathType Leaf)) {
    throw "Missing ArcReel compose file: $composePath"
}

if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
    Copy-Item -LiteralPath $envExamplePath -Destination $envPath -ErrorAction Stop
}

$dataDirectories = @(
    (Join-Path $projectRoot 'data\arcreel\projects'),
    (Join-Path $projectRoot 'data\arcreel\logs'),
    (Join-Path $projectRoot 'data\arcreel\vertex_keys'),
    (Join-Path $projectRoot 'data\arcreel\claude_data')
)

foreach ($directory in $dataDirectories) {
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item -ItemType Directory -Path $directory -Force -ErrorAction Stop | Out-Null
    }
}

& docker compose --project-name automated-video-workbench --project-directory $deployDir -f $composePath up -d
if ($LASTEXITCODE -ne 0) {
    throw "ArcReel Docker Compose startup failed with exit code $LASTEXITCODE"
}

& docker compose --project-name automated-video-workbench --project-directory $deployDir -f $composePath ps
if ($LASTEXITCODE -ne 0) {
    throw "ArcReel Docker Compose status failed with exit code $LASTEXITCODE"
}
