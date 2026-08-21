param(
    [switch]$EnableDingTalk
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$composePath = Join-Path $projectRoot 'deploy\compose.yml'
$envPath = Join-Path $projectRoot '.env'
$envExamplePath = Join-Path $projectRoot '.env.example'

if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
    Copy-Item -LiteralPath $envExamplePath -Destination $envPath
}

$envContent = Get-Content -LiteralPath $envPath -Raw
$randomBytes = New-Object byte[] 36
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($randomBytes)
$generatedSecret = [Convert]::ToBase64String($randomBytes)
$randomPasswordBytes = New-Object byte[] 18
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($randomPasswordBytes)
$generatedPassword = [Convert]::ToBase64String($randomPasswordBytes)

if ($envContent -match '(?m)^AUTH_PASSWORD=\s*$') {
    $envContent = $envContent -replace '(?m)^AUTH_PASSWORD=\s*$', "AUTH_PASSWORD=$generatedPassword"
}
if ($envContent -match '(?m)^AUTH_TOKEN_SECRET=\s*$') {
    $envContent = $envContent -replace '(?m)^AUTH_TOKEN_SECRET=\s*$', "AUTH_TOKEN_SECRET=$generatedSecret"
}
[System.IO.File]::WriteAllText($envPath, $envContent, [System.Text.UTF8Encoding]::new($false))

@(
    'data\arcreel\projects',
    'data\arcreel\logs',
    'data\arcreel\vertex_keys',
    'data\arcreel\claude_data',
    'data\control-plane',
    'data\dingtalk'
) | ForEach-Object {
    New-Item -ItemType Directory -Path (Join-Path $projectRoot $_) -Force | Out-Null
}

$composeArguments = @(
    'compose',
    '--project-name', 'automated-video-workbench',
    '--project-directory', (Join-Path $projectRoot 'deploy'),
    '--env-file', $envPath,
    '-f', $composePath
)
if ($EnableDingTalk) {
    if ($envContent -match '(?m)^DINGTALK_CLIENT_ID=\s*$' -or $envContent -match '(?m)^DINGTALK_CLIENT_SECRET=\s*$') {
        throw 'EnableDingTalk requires DINGTALK_CLIENT_ID and DINGTALK_CLIENT_SECRET in the local .env file.'
    }
    $composeArguments += @('--profile', 'dingtalk')
}
$composeArguments += @('up', '-d', '--build')

& docker @composeArguments
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose failed with exit code $LASTEXITCODE"
}

$deadline = (Get-Date).AddMinutes(3)
do {
    $arcReelState = docker inspect --format '{{.State.Health.Status}}' automated-video-workbench-arcreel-1 2>$null
    $controlPlaneState = docker inspect --format '{{.State.Health.Status}}' automated-video-workbench-control-plane-1 2>$null
    $serviceStates = @($arcReelState, $controlPlaneState)
    if ($serviceStates.Count -eq 2 -and ($serviceStates | Where-Object { $_ -ne 'healthy' }).Count -eq 0) {
        break
    }
    Start-Sleep -Seconds 5
} while ((Get-Date) -lt $deadline)

if ($serviceStates.Count -ne 2 -or ($serviceStates | Where-Object { $_ -ne 'healthy' }).Count -ne 0) {
    & docker compose --project-name automated-video-workbench --project-directory (Join-Path $projectRoot 'deploy') --env-file $envPath -f $composePath ps
    throw "Services did not become healthy: $($serviceStates -join ', ')"
}

[pscustomobject]@{
    ArcReel = 'http://127.0.0.1:1241'
    Workbench = 'http://127.0.0.1:8130'
    ControlPlaneDocs = 'http://127.0.0.1:8130/docs'
    DingTalkEnabled = [bool]$EnableDingTalk
} | Format-List
