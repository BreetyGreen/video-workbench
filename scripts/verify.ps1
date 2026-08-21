$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$verificationDir = Join-Path $projectRoot 'data\control-plane\verification'
$landscapePath = Join-Path $verificationDir 'voice-landscape.mp4'
$verticalPath = Join-Path $verificationDir 'voice-vertical.mp4'
$speechAPath = Join-Path $verificationDir 'speech-a.wav'
$speechBPath = Join-Path $verificationDir 'speech-b.wav'
$controlPlaneBase = 'http://127.0.0.1:8130'
$controlContainer = 'automated-video-workbench-control-plane-1'

New-Item -ItemType Directory -Path $verificationDir -Force | Out-Null

$arcHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:1241/health' -TimeoutSec 15
$controlHealth = Invoke-RestMethod -Uri "$controlPlaneBase/health" -TimeoutSec 15
if ($controlHealth.status -ne 'ok') { throw 'Control-plane health response was not ok' }

& docker exec $controlContainer espeak-ng -v en-us -s 145 -w /data/verification/speech-a.wav 'First, show the final result. This makes the opening much more engaging.'
if ($LASTEXITCODE -ne 0) { throw 'First speech fixture generation failed' }
& docker exec $controlContainer espeak-ng -v en-us -s 155 -w /data/verification/speech-b.wav 'Use a second camera angle, keep the original voice, and generate captions.'
if ($LASTEXITCODE -ne 0) { throw 'Second speech fixture generation failed' }

$ffmpegCommand = Get-Command ffmpeg -ErrorAction Stop
& $ffmpegCommand.Source -hide_banner -loglevel error -y `
    -f lavfi -i 'testsrc2=size=640x360:rate=30' -i $speechAPath `
    -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest $landscapePath
if ($LASTEXITCODE -ne 0) { throw "Landscape fixture generation failed with exit code $LASTEXITCODE" }
& $ffmpegCommand.Source -hide_banner -loglevel error -y `
    -f lavfi -i 'smptebars=size=360x640:rate=30' -i $speechBPath `
    -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest $verticalPath
if ($LASTEXITCODE -ne 0) { throw "Vertical fixture generation failed with exit code $LASTEXITCODE" }

$createResponse = & curl.exe -sS -X POST "$controlPlaneBase/api/tasks" `
    -F 'title=真实语音多素材验收样例' `
    -F 'content_type=pet' `
    -F 'rights_confirmed=true' `
    -F 'quality_profile=fast_preview' `
    -F 'cloud_processing_allowed=false' `
    -F 'requirements_text=竖屏成片，结果前置，删除停顿，自动字幕，统一响度。' `
    -F "reference_file=@$verticalPath;type=video/mp4" `
    -F "files=@$landscapePath;type=video/mp4" `
    -F "files=@$verticalPath;type=video/mp4"
if ($LASTEXITCODE -ne 0) { throw "Task creation failed with exit code $LASTEXITCODE" }
$task = $createResponse | ConvertFrom-Json
if (-not $task.id) { throw "Task creation did not return an id: $createResponse" }

$processed = Invoke-RestMethod -Method Post -Uri "$controlPlaneBase/api/tasks/$($task.id)/process" -TimeoutSec 900
if ($processed.status -ne 'reviewing') { throw "Processed task did not enter reviewing state: $($processed.status)" }

$reviewResponse = Invoke-WebRequest -UseBasicParsing -Uri "$controlPlaneBase/review/$($task.id)" -TimeoutSec 15
if ($reviewResponse.StatusCode -ne 200 -or $reviewResponse.Content -notmatch '剪辑理解证据') {
    throw 'Review page did not expose editing evidence'
}
$manifest = Invoke-RestMethod -Uri "$controlPlaneBase/api/tasks/$($task.id)/manifest" -TimeoutSec 15
if (-not $manifest.artifacts_complete -or -not $manifest.manifest_valid) {
    throw 'Review manifest or required artifacts are incomplete'
}

$artifactDir = Join-Path $projectRoot "data\control-plane\artifacts\$($task.id)"
$draftZip = Join-Path $artifactDir 'draft.zip'
$analysisPath = Join-Path $artifactDir 'analysis\media-analysis.json'
$timelinePath = Join-Path $artifactDir 'edit-timeline.json'
$renderReportPath = Join-Path $artifactDir 'render-report.json'
$qualityReportPath = Join-Path $artifactDir 'quality-report.json'
$referenceBriefPath = Join-Path $artifactDir 'analysis\reference-video-brief.json'
$captionPath = Join-Path $artifactDir 'captions.srt'
$coverPath = Join-Path $artifactDir 'cover.jpg'
@($draftZip, $analysisPath, $timelinePath, $renderReportPath, $qualityReportPath, $referenceBriefPath, $captionPath, $coverPath) | ForEach-Object {
    if (-not (Test-Path -LiteralPath $_ -PathType Leaf)) { throw "Required editing artifact missing: $_" }
}

$analyses = Get-Content -LiteralPath $analysisPath -Raw | ConvertFrom-Json
$timeline = Get-Content -LiteralPath $timelinePath -Raw | ConvertFrom-Json
$renderReport = Get-Content -LiteralPath $renderReportPath -Raw | ConvertFrom-Json
$qualityReport = Get-Content -LiteralPath $qualityReportPath -Raw | ConvertFrom-Json
$transcriptSegments = @($analyses | ForEach-Object { $_.transcript.segments }).Count
if (@($analyses).Count -ne 2) { throw "Expected two media analyses, got $(@($analyses).Count)" }
if ($transcriptSegments -lt 2) { throw "Real transcription did not produce enough segments: $transcriptSegments" }
if ($timeline.source_count -ne 2) { throw "Timeline did not use both materials: $($timeline.source_count)" }
if ($timeline.engine -ne 'reference_guided') { throw "Timeline did not use reference guidance: $($timeline.engine)" }
if ($renderReport.canvas.width -ne 1080 -or $renderReport.canvas.height -ne 1920) {
    throw 'Rendered canvas is not 1080x1920'
}
if ((Get-Item -LiteralPath $captionPath).Length -le 3) { throw 'Caption file is empty' }
if (@($qualityReport.blocking_failures).Count -ne 0) { throw "Quality gates failed: $($qualityReport.blocking_failures -join '; ')" }

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($draftZip)
try {
    $draftInfo = $zip.Entries | Where-Object { $_.FullName -like '*/draft_info.json' } | Select-Object -First 1
    if (-not $draftInfo) { throw 'Draft ZIP does not contain draft_info.json' }
}
finally { $zip.Dispose() }

$integrations = Invoke-RestMethod -Uri "$controlPlaneBase/api/integrations/status" -TimeoutSec 15
[pscustomobject]@{
    ArcReel = if ($arcHealth) { 'ok' } else { 'unknown' }
    ControlPlane = $controlHealth.status
    TaskId = $task.id
    TaskStatus = $processed.status
    ReviewUrl = "$controlPlaneBase/review/$($task.id)"
    DraftZip = $draftZip
    MaterialsAnalyzed = @($analyses).Count
    TranscriptSegments = $transcriptSegments
    TimelineClips = @($timeline.clips).Count
    TimelineSources = $timeline.source_count
    RenderCanvas = "$($renderReport.canvas.width)x$($renderReport.canvas.height)"
    TimelineEngine = $timeline.engine
    QualityStatus = $qualityReport.status
    Dify = $integrations.dify.status
    DingTalk = $integrations.dingtalk.status
} | Format-List
