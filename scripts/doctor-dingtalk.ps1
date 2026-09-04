$ErrorActionPreference = 'Stop'

$candidates = @(
    'B:\DingDing\main\current\DingTalk.exe',
    'B:\Apps\DingTalk\DingTalk.exe',
    (Join-Path $env:LOCALAPPDATA 'DingTalk\main\current\DingTalk.exe'),
    (Join-Path $env:LOCALAPPDATA 'DingTalk\DingTalk.exe')
)
$app = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
$processes = @(Get-Process -Name DingTalk -ErrorAction SilentlyContinue)

if ([string]::IsNullOrWhiteSpace($app)) {
    [pscustomobject]@{
        Installed = $false
        InstallPath = $null
        ProductVersion = $null
        SignatureStatus = $null
        Publisher = $null
        RunningProcesses = $processes.Count
        AppDataNote = 'DingTalk may still create unavoidable per-user profile/cache files under AppData.'
    } | ConvertTo-Json
    exit 1
}

$resolved = (Resolve-Path -LiteralPath $app).Path
$version = (Get-Item -LiteralPath $resolved).VersionInfo.ProductVersion
$signature = Get-AuthenticodeSignature -LiteralPath $resolved

[pscustomobject]@{
    Installed = $true
    InstallPath = $resolved
    ProductVersion = $version
    SignatureStatus = [string]$signature.Status
    Publisher = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
    RunningProcesses = $processes.Count
    ProcessPaths = @($processes | ForEach-Object { $_.Path } | Where-Object { $_ } | Sort-Object -Unique)
    AppDataNote = 'DingTalk may still create unavoidable per-user profile/cache files under AppData; the application binaries can remain on B:.'
} | ConvertTo-Json -Depth 4
