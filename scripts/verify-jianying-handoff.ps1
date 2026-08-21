param(
    [Parameter(Mandatory = $true)]
    [string]$TaskId,
    [string]$DraftRoot = ''
)

$ErrorActionPreference = 'Stop'

$parsedTaskId = [guid]::Empty
if (-not [guid]::TryParse($TaskId, [ref]$parsedTaskId)) {
    throw 'TaskId must be a valid UUID.'
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$artifactRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot 'data\control-plane\artifacts'))
$artifactDirectory = [System.IO.Path]::GetFullPath((Join-Path $artifactRoot $TaskId))
if (-not $artifactDirectory.StartsWith($artifactRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Resolved task artifact directory escaped the configured root.'
}

$requiredArtifacts = @('preview.mp4', 'draft.zip', 'edit-timeline.json', 'quality-report.json', 'review.json')
$missingArtifacts = @($requiredArtifacts | Where-Object { -not (Test-Path -LiteralPath (Join-Path $artifactDirectory $_) -PathType Leaf) })
if ($missingArtifacts.Count -gt 0) {
    throw "Task is missing required handoff artifacts: $($missingArtifacts -join ', ')"
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$draftZip = Join-Path $artifactDirectory 'draft.zip'
$archive = [System.IO.Compression.ZipFile]::OpenRead($draftZip)
try {
    $entries = @($archive.Entries | Where-Object { -not [string]::IsNullOrWhiteSpace($_.Name) })
    $topFolders = @($entries | ForEach-Object { ($_.FullName -replace '\\', '/').Split('/')[0] } | Sort-Object -Unique)
    if ($topFolders.Count -ne 1) {
        throw 'Draft package must contain exactly one top-level directory.'
    }
    if (-not ($entries | Where-Object { ($_.FullName -replace '\\', '/') -like '*/draft_info.json' })) {
        throw 'Draft package does not contain draft_info.json.'
    }
    $draftName = $topFolders[0]
}
finally {
    $archive.Dispose()
}

if ([string]::IsNullOrWhiteSpace($DraftRoot)) {
    $candidateRoots = @(
        'B:\JianyingData\Drafts\JianyingPro Drafts',
        'B:\JianyingData\Drafts',
        (Join-Path $env:LOCALAPPDATA 'JianyingPro\User Data\Projects\com.lveditor.draft'),
        (Join-Path $env:LOCALAPPDATA 'CapCut\User Data\Projects\com.lveditor.draft')
    )
    $DraftRoot = $candidateRoots | Where-Object { Test-Path -LiteralPath $_ -PathType Container } | Select-Object -First 1
}

$importedDirectory = $null
$mediaPathsValidated = $false
if (-not [string]::IsNullOrWhiteSpace($DraftRoot)) {
    $candidate = [System.IO.Path]::GetFullPath((Join-Path $DraftRoot $draftName))
    if (Test-Path -LiteralPath (Join-Path $candidate 'draft_info.json') -PathType Leaf) {
        $importedDirectory = $candidate
        $draftInfo = Get-Content -LiteralPath (Join-Path $candidate 'draft_info.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $missingMedia = @(
            $draftInfo.materials.videos |
                ForEach-Object { $_.path } |
                Where-Object { [string]::IsNullOrWhiteSpace($_) -or -not (Test-Path -LiteralPath $_ -PathType Leaf) }
        )
        $mediaPathsValidated = $missingMedia.Count -eq 0
        if (-not $mediaPathsValidated) {
            throw "Imported draft contains $($missingMedia.Count) unresolved media path(s)."
        }
    }
}

[pscustomobject]@{
    TaskId = $TaskId
    Preview = (Join-Path $artifactDirectory 'preview.mp4')
    DraftPackage = $draftZip
    DraftName = $draftName
    ImportedDirectory = $importedDirectory
    PackageValidated = $true
    MediaPathsValidated = $mediaPathsValidated
    NextStep = if ($importedDirectory) { 'Open this draft in Jianying and perform the final visual check.' } else { 'Run import-jianying-draft.ps1, then re-run this verifier.' }
} | ConvertTo-Json -Depth 3
