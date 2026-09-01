param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$output = Join-Path $PSScriptRoot 'dist'
& $Python -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements-build.txt')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller dependency installation failed.' }
& $Python -m PyInstaller --noconfirm --clean --onefile --name VideoWorkbenchSync `
    --paths (Join-Path $root 'services\control-plane') `
    --hidden-import ctypes --hidden-import datetime --hidden-import platform --hidden-import shutil --hidden-import typing `
    --add-data ((Join-Path $root 'scripts\jianying-host-helper.py') + ';scripts') `
    --distpath $output `
    (Join-Path $root 'scripts\sync-jianying-device.py')
if ($LASTEXITCODE -ne 0) { throw 'Windows sync helper build failed.' }
Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $output 'VideoWorkbenchSync.exe') |
    Select-Object Algorithm,Hash,Path | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $output 'VideoWorkbenchSync.exe.sha256.json') -Encoding utf8
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'install-windows.ps1') -Destination $output -Force
Write-Warning 'Local build is unsigned. Sign the EXE before public distribution.'
