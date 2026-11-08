#!/usr/bin/env bash
# Install local Fun-CosyVoice3 (open-source voice clone) on macOS. Optional: only needed for the local voice route.
# Idempotent: re-run to resume. Needs ~8 GB free (5 GB model + Python env), network, and uv (scripts/bootstrap.sh installs it).
#   COSYVOICE_HOME   install dir (default ~/Library/Application Support/VideoWorkbench/CosyVoice)
#   VIDEO_WORKBENCH_PIP_MIRROR  e.g. https://mirrors.aliyun.com/pypi/simple/ when PyPI is slow
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOME_DIR="${COSYVOICE_HOME:-$HOME/Library/Application Support/VideoWorkbench/CosyVoice}"
COMMIT="074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc"
export UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-300}"
INDEX_ARGS=()
if [ -n "${VIDEO_WORKBENCH_PIP_MIRROR:-}" ]; then INDEX_ARGS=(--index-url "$VIDEO_WORKBENCH_PIP_MIRROR"); fi

# scripts/bootstrap.sh installs uv into ~/.local/bin, which may not be on PATH yet
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
command -v uv >/dev/null 2>&1 || { echo "uv not found: run 'bash scripts/bootstrap.sh' first" >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo "git not found: run 'xcode-select --install'" >&2; exit 1; }

echo "== 1/4 source -> $HOME_DIR"
if [ ! -d "$HOME_DIR/.git" ]; then
  mkdir -p "$(dirname "$HOME_DIR")"
  git clone https://github.com/FunAudioLLM/CosyVoice.git "$HOME_DIR"
fi
git -C "$HOME_DIR" fetch --quiet origin || true
git -C "$HOME_DIR" checkout --quiet "$COMMIT"
git -C "$HOME_DIR" submodule update --init --recursive

echo "== 2/4 Python 3.10 env (CPU)"
cd "$HOME_DIR"
[ -x .venv/bin/python ] || uv venv --python 3.10 .venv
uv pip install --python .venv/bin/python ${INDEX_ARGS[@]+"${INDEX_ARGS[@]}"} torch==2.3.1 torchaudio==2.3.1
uv pip install --python .venv/bin/python ${INDEX_ARGS[@]+"${INDEX_ARGS[@]}"} -r "$HERE/requirements-cpu.txt" \
  --build-constraints "$HERE/build-constraints.txt"
uv pip install --python .venv/bin/python ${INDEX_ARGS[@]+"${INDEX_ARGS[@]}"} setuptools==69.5.1   # runtime needs pkg_resources

echo "== 3/4 model Fun-CosyVoice3-0.5B from ModelScope (~5 GB, resumable)"
.venv/bin/python - <<'PY'
from modelscope import snapshot_download
snapshot_download("FunAudioLLM/Fun-CosyVoice3-0.5B-2512", local_dir="pretrained_models/Fun-CosyVoice3-0.5B",
                  ignore_file_pattern=["llm.rl.pt", "flow.decoder.estimator.fp32.onnx", "speech_tokenizer_v3.batch.onnx"])
print("model ok")
PY

echo "== 4/4 smoke test (official demo voice, a few minutes on CPU)"
OUT="$HOME_DIR/smoke-test.wav"
.venv/bin/python "$HERE/clone_tts.py" --prompt "$HOME_DIR/asset/zero_shot_prompt.wav" \
  --prompt-text "希望你以后能够做的比我还好呦。" --text "你好，这是本机配音测试。" --out "$OUT"
echo
echo "CosyVoice ready. Use it with:"
echo "  COSYVOICE_HOME=\"$HOME_DIR\" \"$HOME_DIR/.venv/bin/python\" $HERE/clone_tts.py --prompt <your.wav> --prompt-text \"<transcript>\" --text-file copy.json --out voice/me/whole.wav"
