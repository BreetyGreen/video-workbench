"""Local voice clone / style TTS with Fun-CosyVoice3 (CPU is enough; slow but free and offline after install).

Install once: macOS `bash tools/cosyvoice/install.sh`, Windows `powershell -File tools/cosyvoice/install.ps1`.
Run with the CosyVoice venv python (install prints the exact command):
  <COSYVOICE_HOME>/.venv/bin/python tools/cosyvoice/clone_tts.py --prompt my_voice.wav --prompt-text "录音原话" \
      --text-file <work>/copy.json --out <work>/voice/my_voice/whole.wav
  --style happy|fast|loud|soft|none   official instruct styles (instead of plain zero-shot)
  --speed 1.0                          speaking speed (prefer 1.0 and let narration_from_whole.py speed it up)

The prompt should be 3-10 s of clean speech (no music) plus its exact transcript.
Only clone your own voice or a voice you have written permission to use.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path


def cosyvoice_home() -> Path:
    if os.environ.get("COSYVOICE_HOME"):
        return Path(os.environ["COSYVOICE_HOME"]).expanduser()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sample-cut"))
    from vw_common import data_home  # stdlib-only module
    return data_home() / "CosyVoice"


CWD = Path.cwd()  # resolve user paths against where the command was run, before chdir below
ROOT = cosyvoice_home()
if not (ROOT / "cosyvoice").is_dir():
    raise SystemExit(f"CosyVoice not installed at {ROOT}. Run tools/cosyvoice/install.sh (macOS) or install.ps1 (Windows), "
                     "or set COSYVOICE_HOME.")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "third_party" / "Matcha-TTS"))
os.chdir(ROOT)  # the model yaml refers to paths relative to the repo

import torch  # noqa: E402
import torchaudio  # noqa: E402
from cosyvoice.cli.cosyvoice import AutoModel  # noqa: E402

SYS = "You are a helpful assistant."
STYLES = {
    "happy": f"{SYS} 请非常开心地说一句话。<|endofprompt|>",
    "fast": f"{SYS} 请用尽可能快地语速说一句话。<|endofprompt|>",
    "loud": f"{SYS} Please say a sentence as loudly as possible.<|endofprompt|>",
    "soft": f"{SYS} Please say a sentence in a very soft voice.<|endofprompt|>",
}

ap = argparse.ArgumentParser()
ap.add_argument("--prompt", required=True)
ap.add_argument("--prompt-text", default="")
ap.add_argument("--text")
ap.add_argument("--text-file")
ap.add_argument("--style", default="none", choices=["none", *STYLES])
ap.add_argument("--speed", type=float, default=1.0)
ap.add_argument("--out", required=True)
ap.add_argument("--model", default=str(ROOT / "pretrained_models" / "Fun-CosyVoice3-0.5B"))
a = ap.parse_args()
user_path = lambda x: Path(x) if Path(x).is_absolute() else CWD / x
prompt = str(user_path(a.prompt))
out = user_path(a.out)

if a.text_file:
    data = json.loads(user_path(a.text_file).read_text(encoding="utf-8"))
    text = "".join(s["text"] for s in data["sentences"]) if isinstance(data, dict) else str(data)
else:
    text = a.text
assert text, "need --text or --text-file"

t0 = time.time()
tts = AutoModel(model_dir=a.model)
print(f"model loaded in {time.time() - t0:.1f}s, sr={tts.sample_rate}", flush=True)

t1 = time.time()
if a.style == "none":
    gen = tts.inference_zero_shot(text, f"{SYS}<|endofprompt|>{a.prompt_text}", prompt, stream=False, speed=a.speed)
else:
    gen = tts.inference_instruct2(text, STYLES[a.style], prompt, stream=False, speed=a.speed)
wav = torch.cat([j["tts_speech"] for j in gen], dim=1)
out.parent.mkdir(parents=True, exist_ok=True)
torchaudio.save(str(out), wav, tts.sample_rate)
dur = wav.shape[1] / tts.sample_rate
el = time.time() - t1
print(json.dumps({"out": str(out), "audio_s": round(dur, 2), "compute_s": round(el, 1), "rtf": round(el / dur, 2),
                  "style": a.style, "speed": a.speed}, ensure_ascii=False))
