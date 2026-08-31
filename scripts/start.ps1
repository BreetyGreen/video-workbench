param(
    [switch]$EnableDingTalk
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$composePath = Join-Path $projectRoot 'deploy\compose.yml'
$envPath = Join-Path $projectRoot '.env'
$envExamplePath = Join-Path $projectRoot '.env.example'

function Test-WorkbenchHealth {
    param([int]$Port)
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3
        return $health.status -eq 'ok'
    }
    catch {
        return $false
    }
}

function Test-LoopbackPortAvailable {
    param([int]$Port)
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    try {
        $listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        $listener.Stop()
    }
}

$existingContainer = $null
$inspection = docker inspect automated-video-workbench-control-plane-1 2>$null
if ($LASTEXITCODE -eq 0 -and $inspection) {
    $existingContainer = $inspection | ConvertFrom-Json | Select-Object -First 1
}

$existingDataMount = $existingContainer.Mounts |
    Where-Object { $_.Destination -eq '/data' -and $_.Type -eq 'bind' } |
    Select-Object -First 1
if ($existingDataMount -and (Test-Path -LiteralPath $existingDataMount.Source -PathType Container)) {
    $env:WORKBENCH_HOST_DATA_DIR = $existingDataMount.Source
}
else {
    $env:WORKBENCH_HOST_DATA_DIR = Join-Path $projectRoot 'data\control-plane'
}

$jianyingDraftCandidates = @(
    'B:\JianyingData\Drafts\JianyingPro Drafts',
    (Join-Path $env:LOCALAPPDATA 'JianyingPro\User Data\Projects\com.lveditor.draft'),
    (Join-Path $env:LOCALAPPDATA 'CapCut\User Data\Projects\com.lveditor.draft')
)
$jianyingDraftRoot = $jianyingDraftCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Container } | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($jianyingDraftRoot)) {
    $jianyingDraftRoot = Join-Path $env:WORKBENCH_HOST_DATA_DIR 'jianying-drafts'
    New-Item -ItemType Directory -Path $jianyingDraftRoot -Force | Out-Null
}
$env:WORKBENCH_HOST_JIANYING_DRAFT_DIR = [System.IO.Path]::GetFullPath($jianyingDraftRoot)

$workbenchPort = 8130
$existingPort = $existingContainer.NetworkSettings.Ports.'8130/tcp' | Select-Object -First 1
if ($existingPort -and $existingPort.HostPort -and (Test-WorkbenchHealth -Port ([int]$existingPort.HostPort))) {
    $workbenchPort = [int]$existingPort.HostPort
}
elseif (-not (Test-LoopbackPortAvailable -Port $workbenchPort)) {
    $workbenchPort++
    while ($workbenchPort -le 8999 -and -not (Test-LoopbackPortAvailable -Port $workbenchPort)) {
        $workbenchPort++
    }
    if ($workbenchPort -gt 8999) {
        throw 'No available loopback port found between 8130 and 8999.'
    }
}
$env:WORKBENCH_HOST_PORT = [string]$workbenchPort
$workbenchUrl = "http://127.0.0.1:$workbenchPort"

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

$hostDeadline = (Get-Date).AddMinutes(2)
do {
    if (Test-WorkbenchHealth -Port $workbenchPort) {
        break
    }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $hostDeadline)
if (-not (Test-WorkbenchHealth -Port $workbenchPort)) {
    throw "Control plane is healthy inside Docker but unavailable at $workbenchUrl."
}

$pythonCommand = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if (-not $pythonCommand) { $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue }
if (-not $pythonCommand) { $pythonCommand = Get-Command python -ErrorAction SilentlyContinue }
if ($pythonCommand) {
    $helperScript = Join-Path $projectRoot 'scripts\jianying-host-helper.py'
    $helperArgumentLine = '"' + $helperScript + '" --data-dir "' + $env:WORKBENCH_HOST_DATA_DIR + '" --container-draft-root /jianying-drafts --fallback-draft-root "' + $env:WORKBENCH_HOST_JIANYING_DRAFT_DIR + '" --watch'
    Start-Process -FilePath $pythonCommand.Source -ArgumentList $helperArgumentLine -WindowStyle Hidden | Out-Null
}

[pscustomobject]@{
    ArcReel = 'http://127.0.0.1:1241'
    Workbench = $workbenchUrl
    ControlPlaneDocs = "$workbenchUrl/docs"
    DataDirectory = $env:WORKBENCH_HOST_DATA_DIR
    JianyingDraftDirectory = $env:WORKBENCH_HOST_JIANYING_DRAFT_DIR
    DingTalkEnabled = [bool]$EnableDingTalk
} | Format-List
