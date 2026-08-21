$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$composePath = Join-Path $projectRoot 'deploy\compose.yml'
$envPath = Join-Path $projectRoot '.env'

& docker compose `
    --project-name automated-video-workbench `
    --project-directory (Join-Path $projectRoot 'deploy') `
    --env-file $envPath `
    -f $composePath `
    down
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose stop failed with exit code $LASTEXITCODE"
}
