"""Local voice clone / style TTS with Fun-CosyVoice3 (CPU is enough; slow but free and offline after install).

Install once: macOS `bash tools/cosyvoice/install.sh`, Windows `powershell -File tools/cosyvoice/install.ps1`.
Run with the CosyVoice venv python (install prints the exact command):
  <COSYVOICE_HOME>/.venv/bin/python tools/cosyvoice/clone_tts.py --prompt my_voice.wav --prompt-text "录音原话" \
      --text-file <work>/copy.json --out <work>/voice/my_voice/whole.wav
  --style sales|happy|fast|loud|soft|none   instruct styles (instead of plain zero-shot); sales = lively seller read
  --instruct "请用…的语气说一句话。"          free-form instruct text (overrides --style)
  --jobs jobs.json                           batch: [{"prompt","prompt_text","text","out",["style"],["instruct"]}],
                                             the model is loaded once (use for previews of many voices)
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
    "sales": f"{SYS} 请用热情洋溢、充满活力、语速稍快的带货主播语气说一句话。<|endofprompt|>",
}

ap = argparse.ArgumentParser()
ap.add_argument("--prompt")
ap.add_argument("--prompt-text", default="")
ap.add_argument("--text")
ap.add_argument("--text-file")
ap.add_argument("--style", default="none", choices=["none", *STYLES])
ap.add_argument("--speed", type=float, default=1.0)
ap.add_argument("--out")
ap.add_argument("--instruct", help="free-form instruct sentence, e.g. 请用温柔亲切的语气说一句话。")
ap.add_argument("--jobs", help="JSON list of jobs; loads the model once")
ap.add_argument("--model", default=str(ROOT / "pretrained_models" / "Fun-CosyVoice3-0.5B"))
a = ap.parse_args()
user_path = lambda x: Path(x) if Path(x).is_absolute() else CWD / x


def read_text(job: dict) -> str:
    if job.get("text_file"):
        data = json.loads(user_path(job["text_file"]).read_text(encoding="utf-8"))
        return "".join(s["text"] for s in data["sentences"]) if isinstance(data, dict) else str(data)
    return job.get("text") or ""


if a.jobs:
    jobs = json.loads(user_path(a.jobs).read_text(encoding="utf-8"))
else:
    if not a.prompt or not a.out:
        raise SystemExit("need --prompt and --out (or --jobs)")
    jobs = [{"prompt": a.prompt, "prompt_text": a.prompt_text, "text": a.text, "text_file": a.text_file,
             "style": a.style, "instruct": a.instruct, "speed": a.speed, "out": a.out}]
for j in jobs:
    assert read_text(j), "need --text or --text-file"

t0 = time.time()
tts = AutoModel(model_dir=a.model)
print(f"model loaded in {time.time() - t0:.1f}s, sr={tts.sample_rate}", flush=True)

for j in jobs:
    text, prompt, out = read_text(j), str(user_path(j["prompt"])), user_path(j["out"])
    style, speed = j.get("style") or "none", float(j.get("speed") or 1.0)
    instruct = f"{SYS} {j['instruct'].strip()}<|endofprompt|>" if j.get("instruct") else STYLES.get(style)
    t1 = time.time()
    if instruct:
        gen = tts.inference_instruct2(text, instruct, prompt, stream=False, speed=speed)
    else:
        gen = tts.inference_zero_shot(text, f"{SYS}<|endofprompt|>{j.get('prompt_text') or ''}", prompt, stream=False,
                                      speed=speed)
    wav = torch.cat([k["tts_speech"] for k in gen], dim=1)
    out.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(out), wav, tts.sample_rate)
    dur = wav.shape[1] / tts.sample_rate
    el = time.time() - t1
    print(json.dumps({"out": str(out), "audio_s": round(dur, 2), "compute_s": round(el, 1), "rtf": round(el / dur, 2),
                      "style": "instruct" if j.get("instruct") else style, "speed": speed}, ensure_ascii=False), flush=True)
