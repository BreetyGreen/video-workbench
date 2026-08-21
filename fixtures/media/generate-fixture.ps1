$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$outputDir = Join-Path $projectRoot 'fixtures\media'
$outputPath = Join-Path $outputDir 'fixture.mp4'
$ffmpegCommand = Get-Command ffmpeg -ErrorAction Stop

New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
& $ffmpegCommand.Source `
    -hide_banner -loglevel error `
    -f lavfi -i 'testsrc2=size=320x240:rate=25' `
    -f lavfi -i 'sine=frequency=1000:sample_rate=48000' `
    -t 2 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest `
    $outputPath

if ($LASTEXITCODE -ne 0) {
    throw "FFmpeg fixture generation failed with exit code $LASTEXITCODE"
}

Get-Item -LiteralPath $outputPath
