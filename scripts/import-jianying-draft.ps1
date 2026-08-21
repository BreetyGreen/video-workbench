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
$sourceZip = [System.IO.Path]::GetFullPath((Join-Path $artifactRoot "$TaskId\draft.zip"))
if (-not $sourceZip.StartsWith($artifactRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Resolved draft package escaped the artifact root.'
}
if (-not (Test-Path -LiteralPath $sourceZip -PathType Leaf)) {
    throw "Draft package not found: $sourceZip"
}

if ([string]::IsNullOrWhiteSpace($DraftRoot)) {
    $candidateRoots = @(
        'B:\JianyingData\Drafts\JianyingPro Drafts',
        'B:\JianyingData\Drafts',
        'B:\Apps\JianyingPro Drafts',
        (Join-Path $env:LOCALAPPDATA 'JianyingPro\User Data\Projects\com.lveditor.draft'),
        (Join-Path $env:LOCALAPPDATA 'CapCut\User Data\Projects\com.lveditor.draft')
    )
    $DraftRoot = $candidateRoots | Where-Object { Test-Path -LiteralPath $_ -PathType Container } | Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($DraftRoot)) {
        throw 'No Jianying/CapCut draft directory was found. Install and open Jianying once, or pass -DraftRoot explicitly.'
    }
}

$resolvedDraftRoot = [System.IO.Path]::GetFullPath($DraftRoot)
if (-not (Test-Path -LiteralPath $resolvedDraftRoot -PathType Container)) {
    throw "DraftRoot does not exist: $resolvedDraftRoot"
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($sourceZip)
try {
    $fileEntries = @($archive.Entries | Where-Object { -not [string]::IsNullOrEmpty($_.Name) })
    if ($fileEntries.Count -eq 0) {
        throw 'Draft package contains no files.'
    }
    $topFolders = @(
        $fileEntries |
            ForEach-Object { ($_.FullName -replace '\\', '/').Split('/')[0] } |
            Sort-Object -Unique
    )
    if ($topFolders.Count -ne 1 -or [string]::IsNullOrWhiteSpace($topFolders[0])) {
        throw 'Draft package must contain exactly one top-level draft directory.'
    }
    foreach ($entry in $fileEntries) {
        $normalized = $entry.FullName -replace '\\', '/'
        if ($normalized.StartsWith('/') -or $normalized -match '(^|/)\.\.(/|$)') {
            throw "Unsafe path in draft package: $($entry.FullName)"
        }
    }
    if (-not ($fileEntries | Where-Object { ($_.FullName -replace '\\', '/') -like '*/draft_info.json' })) {
        throw 'Draft package does not contain draft_info.json.'
    }

    $destination = [System.IO.Path]::GetFullPath((Join-Path $resolvedDraftRoot $topFolders[0]))
    if (-not $destination.StartsWith($resolvedDraftRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Resolved destination escaped DraftRoot.'
    }
    if (Test-Path -LiteralPath $destination) {
        throw "Destination already exists; no files were overwritten: $destination"
    }
}
finally {
    $archive.Dispose()
}

Expand-Archive -LiteralPath $sourceZip -DestinationPath $resolvedDraftRoot -ErrorAction Stop

# Drafts are built inside the Linux container, so their media paths point at
# /data/... until the package reaches Windows. Relink only this freshly
# imported package to its own bundled assets; never scan or rewrite other
# Jianying projects.
$sourceDraftPrefix = "/data/artifacts/$TaskId/drafts/$($topFolders[0])"
$jsonDestination = $destination.Replace('\', '\\')
$rewrittenPaths = 0
foreach ($jsonName in @('draft_info.json', 'draft_content.json', 'draft_meta_info.json')) {
    $jsonPath = Join-Path $destination $jsonName
    if (-not (Test-Path -LiteralPath $jsonPath -PathType Leaf)) {
        continue
    }
    $content = Get-Content -LiteralPath $jsonPath -Raw -Encoding UTF8
    $matches = ([regex]::Matches($content, [regex]::Escape($sourceDraftPrefix))).Count
    if ($matches -gt 0) {
        $updated = $content.Replace($sourceDraftPrefix, $jsonDestination)
        Set-Content -LiteralPath $jsonPath -Value $updated -Encoding UTF8 -NoNewline
        $rewrittenPaths += $matches
    }
}

$draftInfoPath = Join-Path $destination 'draft_info.json'
$draftInfo = Get-Content -LiteralPath $draftInfoPath -Raw -Encoding UTF8 | ConvertFrom-Json
$missingMediaPaths = @(
    $draftInfo.materials.videos |
        ForEach-Object { $_.path } |
        Where-Object { [string]::IsNullOrWhiteSpace($_) -or -not (Test-Path -LiteralPath $_ -PathType Leaf) }
)
if ($missingMediaPaths.Count -gt 0) {
    throw "Imported draft contains $($missingMediaPaths.Count) unresolved media path(s)."
}

[pscustomobject]@{
    TaskId = $TaskId
    SourceZip = $sourceZip
    DraftDirectory = $destination
    Imported = (Test-Path -LiteralPath (Join-Path $destination 'draft_info.json') -PathType Leaf)
    PathsRelinked = ($rewrittenPaths -gt 0)
    RewrittenPathCount = $rewrittenPaths
    MediaPathsValidated = ($missingMediaPaths.Count -eq 0)
    CompatibilityValidated = $false
    NextStep = 'Open Jianying and verify this draft manually before marking compatibility as validated.'
} | ConvertTo-Json -Depth 3
