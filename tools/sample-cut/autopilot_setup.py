"""One-time setup for autopilot (idempotent): fonts, BGM library, default settings, readiness report.

usage: python autopilot_setup.py [--own-voice my.wav --own-voice-text "录音原话"] [--cloud-voice longxiaochun_v2]
                                 [--deliveries <dir>] [--jianying-draft]
writes <data_home>/sample-cut.json. Never asks for or prints a key: a DashScope key is read from the environment only.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from vw_common import IS_WIN, data_home, dashscope_key

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--own-voice")
ap.add_argument("--own-voice-text")
ap.add_argument("--cloud-voice")
ap.add_argument("--deliveries")
ap.add_argument("--jianying-draft", action="store_true")
ap.add_argument("--skip-downloads", action="store_true")
a = ap.parse_args()

cfg_path = data_home() / "sample-cut.json"
cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
cfg.setdefault("voice_engine", "auto")
cfg.setdefault("cloud_voice", "longxiaochun_v2")
cfg.setdefault("bgm_versions", 3)
cfg.setdefault("bgm_lufs", -20.0)  # music level: -20 ≈ 8-10 dB under the voice on a phone; -18 louder, -23 quieter
if a.cloud_voice:
    cfg["cloud_voice"] = a.cloud_voice
if a.own_voice:
    p = Path(a.own_voice).expanduser().resolve()
    if not p.is_file() or not a.own_voice_text:
        raise SystemExit("--own-voice needs an existing 3-10 s wav and --own-voice-text with its exact words")
    dst = data_home() / "own-voice" / p.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dst)
    cfg["own_voice_prompt"], cfg["own_voice_text"] = str(dst), a.own_voice_text
if a.deliveries:
    cfg["deliveries_dir"] = str(Path(a.deliveries).expanduser())
if a.jianying_draft:
    cfg["jianying_draft"] = True
cfg_path.parent.mkdir(parents=True, exist_ok=True)
cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")


def run(script, *args):
    r = subprocess.run([sys.executable, str(HERE / script), *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    print(f"--- {script}: {(r.stdout.strip().splitlines() or [''])[-1]}")
    return r.returncode == 0


if not a.skip_downloads:
    run("fonts_download.py")
    bgm = Path(os.environ.get("VIDEO_WORKBENCH_BGM_DIR") or data_home() / "bgm-library" / "incompetech")
    if not (bgm / "manifest.json").is_file():
        run("bgm_pick.py", "30") and run("bgm_download.py")

font_man = Path(os.environ.get("VIDEO_WORKBENCH_FONT_DIR") or data_home() / "fonts") / "manifest.json"
fonts = json.loads(font_man.read_text(encoding="utf-8")) if font_man.is_file() else {}
bgm_man = Path(os.environ.get("VIDEO_WORKBENCH_BGM_DIR") or data_home() / "bgm-library" / "incompetech") / "manifest.json"
try:
    key = bool(dashscope_key())
except SystemExit:
    key = False
cv = Path(os.environ.get("COSYVOICE_HOME") or cfg.get("cosyvoice_home") or data_home() / "CosyVoice")
cv_ok = (cv / (".venv/Scripts/python.exe" if IS_WIN else ".venv/bin/python")).exists()
ready = {
    "ffmpeg": bool(shutil.which("ffmpeg")),
    "fonts": f"{sum(1 for f in fonts.values() if f.get('sha256'))}/{len(fonts) or 6}",
    "bgm_tracks": len(json.loads(bgm_man.read_text(encoding="utf-8"))) if bgm_man.is_file() else 0,
    "dashscope_key": key,
    "cosyvoice_installed": cv_ok,
    "own_voice": bool(cfg.get("own_voice_prompt")),
    "voice_route": ("本机克隆自己的声音" if cfg.get("own_voice_prompt") and cv_ok else
                    f"云端 {cfg['cloud_voice']}" if key else
                    "本机 CosyVoice 示例音色（仅演示）" if cv_ok else "缺：需要百炼 Key 或安装 CosyVoice"),
    "timing": "语音识别逐字对齐" if key else "按字数估算（无 Key）",
    "settings": str(cfg_path),
}
print(json.dumps(ready, ensure_ascii=False, indent=1))
sys.exit(0 if ready["ffmpeg"] and (key or cv_ok) else 1)
