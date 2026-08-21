$ErrorActionPreference = 'Stop'

$candidateRoots = @(
    'B:\Apps\JianyingPro',
    'B:\Apps\CapCut',
    (Join-Path $env:LOCALAPPDATA 'JianyingPro\Apps'),
    (Join-Path $env:LOCALAPPDATA 'JianyingPro'),
    (Join-Path $env:LOCALAPPDATA 'CapCut\Apps'),
    (Join-Path $env:LOCALAPPDATA 'CapCut')
)

$existingRoots = @($candidateRoots | Where-Object { Test-Path -LiteralPath $_ -PathType Container })
$executables = @()
foreach ($candidateRoot in $existingRoots) {
    $executables += Get-ChildItem -LiteralPath $candidateRoot -Filter '*.exe' -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match 'Jianying|CapCut' } |
        Select-Object -ExpandProperty FullName
}

[pscustomobject]@{
    Installed = $executables.Count -gt 0
    CandidateRoots = $candidateRoots
    Executables = @($executables | Sort-Object -Unique)
    DraftCompatibilityValidated = $false
} | ConvertTo-Json -Depth 4
