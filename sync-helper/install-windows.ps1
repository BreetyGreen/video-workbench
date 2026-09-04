param(
    [Parameter(Mandatory = $true)][ValidatePattern('^https://')][string]$ServerUrl,
    [string]$InstallDir = '',
    [string]$DataDir = ''
)
$ErrorActionPreference = 'Stop'
$preferredRoot = $env:LOCALAPPDATA
if ([string]::IsNullOrWhiteSpace($preferredRoot)) { throw 'LOCALAPPDATA is unavailable for the current Windows user.' }
if ([string]::IsNullOrWhiteSpace($InstallDir)) { $InstallDir = Join-Path $preferredRoot 'Apps\VideoWorkbenchSync' }
if ([string]::IsNullOrWhiteSpace($DataDir)) { $DataDir = Join-Path $preferredRoot 'VideoWorkbench\Sync' }
$source = Join-Path $PSScriptRoot 'VideoWorkbenchSync.exe'
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    $source = Join-Path $PSScriptRoot 'dist\VideoWorkbenchSync.exe'
}
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw 'Build VideoWorkbenchSync.exe first.' }
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
$destination = Join-Path $InstallDir 'VideoWorkbenchSync.exe'
Copy-Item -LiteralPath $source -Destination $destination -Force
Write-Host '首次配对：请粘贴服务器配置助手刚生成的一次性配对码。'
& $destination --server-url $ServerUrl --data-dir $DataDir
if ($LASTEXITCODE -ne 0) { throw 'Device pairing or initial sync failed; startup task was not registered.' }
$action = New-ScheduledTaskAction -Execute $destination -Argument "--server-url `"$ServerUrl`" --data-dir `"$DataDir`" --watch"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'VideoWorkbenchSync' -Action $action -Trigger $trigger -Settings $settings -Description '同步服务器成片到本机剪映' -Force | Out-Null
Write-Warning 'Public distribution requires an Authenticode-signed executable.'
