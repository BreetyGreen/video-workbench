# Install local Fun-CosyVoice3 (open-source voice clone) on Windows. Optional: only for the local voice route.
# Idempotent: re-run to resume. Needs ~8 GB free, network, uv and git.
#   $env:COSYVOICE_HOME             install dir (default <repo>\data\CosyVoice)
#   $env:VIDEO_WORKBENCH_PIP_MIRROR e.g. https://mirrors.aliyun.com/pypi/simple/ when PyPI is slow
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = (Resolve-Path (Join-Path $Here "..\..")).Path
$HomeDir = if ($env:COSYVOICE_HOME) { $env:COSYVOICE_HOME } else { Join-Path $Repo "data\CosyVoice" }
$Commit = "074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc"
if (-not $env:UV_HTTP_TIMEOUT) { $env:UV_HTTP_TIMEOUT = "300" }
$Index = @(); if ($env:VIDEO_WORKBENCH_PIP_MIRROR) { $Index = @("--index-url", $env:VIDEO_WORKBENCH_PIP_MIRROR) }
foreach ($c in "uv", "git") { if (-not (Get-Command $c -ErrorAction SilentlyContinue)) { throw "$c not found (run scripts\bootstrap.ps1 first)" } }

Write-Host "== 1/4 source -> $HomeDir"
if (-not (Test-Path (Join-Path $HomeDir ".git"))) { git clone https://github.com/FunAudioLLM/CosyVoice.git $HomeDir }
git -C $HomeDir fetch --quiet origin 2>$null
git -C $HomeDir checkout --quiet $Commit
git -C $HomeDir submodule update --init --recursive

Write-Host "== 2/4 Python 3.10 env (CPU)"
Push-Location $HomeDir
try {
  $Py = Join-Path $HomeDir ".venv\Scripts\python.exe"
  if (-not (Test-Path $Py)) { uv venv --python 3.10 .venv }
  uv pip install --python $Py torch==2.3.1 torchaudio==2.3.1 --index-url https://download.pytorch.org/whl/cpu
  uv pip install --python $Py @Index -r (Join-Path $Here "requirements-cpu.txt") --build-constraints (Join-Path $Here "build-constraints.txt")
  uv pip install --python $Py @Index setuptools==69.5.1
  if ($LASTEXITCODE) { throw "pip install failed" }

  Write-Host "== 3/4 model Fun-CosyVoice3-0.5B from ModelScope (~5 GB, resumable)"
  $code = @'
from modelscope import snapshot_download
snapshot_download("FunAudioLLM/Fun-CosyVoice3-0.5B-2512", local_dir="pretrained_models/Fun-CosyVoice3-0.5B",
                  ignore_file_pattern=["llm.rl.pt", "flow.decoder.estimator.fp32.onnx", "speech_tokenizer_v3.batch.onnx"])
print("model ok")
'@
  if (-not (Test-Path "pretrained_models\Fun-CosyVoice3-0.5B\llm.pt")) { $code | & $Py - ; if ($LASTEXITCODE) { throw "model download failed" } }

  Write-Host "== 4/4 smoke test (official demo voice, a few minutes on CPU)"
  $env:COSYVOICE_HOME = $HomeDir
  & $Py (Join-Path $Here "clone_tts.py") --prompt (Join-Path $HomeDir "asset\zero_shot_prompt.wav") `
    --prompt-text "希望你以后能够做的比我还好呦。" --text "你好，这是本机配音测试。" --out (Join-Path $HomeDir "smoke-test.wav")
  if ($LASTEXITCODE) { throw "smoke test failed" }
} finally { Pop-Location }
Write-Host "`nCosyVoice ready:  `$env:COSYVOICE_HOME='$HomeDir'; & '$Py' $Here\clone_tts.py --prompt <your.wav> --prompt-text '<transcript>' --text-file copy.json --out voice\me\whole.wav"
