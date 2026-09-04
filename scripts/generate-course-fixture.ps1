$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$fixtureRoot = Join-Path $projectRoot 'fixtures\dingtalk\media'
$ffmpeg = (Get-Command ffmpeg -ErrorAction Stop).Source
New-Item -ItemType Directory -Path $fixtureRoot -Force | Out-Null

$outputs = @(
    @{ Name = 'reference.mp4'; Color = '0x18181b'; Frequency = 440 },
    @{ Name = 'material-red.mp4'; Color = '0xdc2626'; Frequency = 520 },
    @{ Name = 'material-green.mp4'; Color = '0x16a34a'; Frequency = 600 },
    @{ Name = 'material-blue.mp4'; Color = '0x2563eb'; Frequency = 680 }
)

foreach ($item in $outputs) {
    $target = Join-Path $fixtureRoot $item.Name
    & $ffmpeg -hide_banner -loglevel error -y `
        -f lavfi -i "color=c=$($item.Color):s=540x960:r=25" `
        -f lavfi -i "sine=frequency=$($item.Frequency):sample_rate=48000" `
        -t 3 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest $target
    if ($LASTEXITCODE -ne 0) { throw "Failed to generate $($item.Name)" }
}

Write-Host "Course fixture media generated in $fixtureRoot"
