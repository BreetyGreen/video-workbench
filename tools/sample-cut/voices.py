"""Preset voice library for the local voice (CosyVoice zero-shot clone). No cloud, no key.

usage (uv run --project tools/sample-cut python tools/sample-cut/voices.py ...):
  add <audio> --name 女声活泼 --text "录音里的每一个字" --consent own|permission [--who "张三，书面同意 2026-11-09"]
      [--tags 女声,活泼] [--style none|happy] [--default] [--preview]
  list                     the library as JSON
  default <name>           voice used when a video doesn't name one
  preview <name> [--text]  synthesize a short sample -> <voice dir>/试听.wav (takes a few minutes on CPU)
  remove <name>            delete one preset (only the copy in the library; the original recording is untouched)

Each preset is <voices dir>/<name>/prompt.wav (5-15 s, mono 24 kHz, levelled, silence trimmed) + voice.json.
voices dir: VIDEO_WORKBENCH_VOICES_DIR, else <data_home>/voices.

Consent is required for every preset: "own" = the user's own voice, "permission" = a person who gave written
permission (record who/when in --who). "demo" is reserved for CosyVoice's bundled sample (tests only).
Never add a voice cut from other people's videos or a third-party model of a real or branded voice.
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from vw_common import IS_WIN, REPO, data_home, probe_dur, run  # noqa: E402

CONSENT = {"own": "本人的声音", "permission": "已获本人书面授权", "demo": "CosyVoice 官方示例（仅演示）"}
PREVIEW_TEXT = "宝子们看过来，这款真的超好喝，冰冰凉凉一口下去，太舒服啦！"


def voices_dir() -> Path:
    return Path(os.environ.get("VIDEO_WORKBENCH_VOICES_DIR") or data_home() / "voices").expanduser()


def cfg_path() -> Path:
    return data_home() / "sample-cut.json"


def load_cfg() -> dict:
    p = cfg_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def save_cfg(cfg: dict) -> None:
    cfg_path().parent.mkdir(parents=True, exist_ok=True)
    cfg_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")


def safe_name(name: str) -> str:
    n = re.sub(r'[\\/:*?"<>|\s]+', "_", name.strip()).strip("._")
    if not n:
        raise SystemExit("音色名字不能为空")
    return n


def cosyvoice() -> tuple[Path, Path]:
    home = Path(os.environ.get("COSYVOICE_HOME") or load_cfg().get("cosyvoice_home") or data_home() / "CosyVoice").expanduser()
    return home, home / (".venv/Scripts/python.exe" if IS_WIN else ".venv/bin/python")


def migrate_legacy() -> None:
    """autopilot_setup.py --own-voice (single voice) -> a preset named 我的声音, once."""
    cfg = load_cfg()
    p = cfg.get("own_voice_prompt")
    if not p or cfg.get("own_voice_migrated") or not Path(p).is_file():
        return
    d = voices_dir() / "我的声音"
    if not (d / "voice.json").is_file():
        _store(Path(p), "我的声音", cfg.get("own_voice_text", ""), "own", "", [], "none")
    cfg["own_voice_migrated"] = True
    cfg.setdefault("default_voice", "我的声音")
    save_cfg(cfg)


def library() -> list[dict]:
    migrate_legacy()
    out = []
    root = voices_dir()
    for j in sorted(root.glob("*/voice.json")) if root.is_dir() else []:
        v = json.loads(j.read_text(encoding="utf-8"))
        if (j.parent / "prompt.wav").is_file():
            out.append({**v, "dir": str(j.parent), "prompt": str(j.parent / "prompt.wav")})
    return out


def pick(name: str | None = None, copy: dict | None = None) -> dict | None:
    """Explicit name > copy.json "voice" > default_voice in settings > the only/first preset. None = empty library."""
    lib = library()
    if not lib:
        return None
    by = {v["name"]: v for v in lib}
    for want, why in ((name, "--voice-name"), ((copy or {}).get("voice"), 'copy.json "voice"'),
                      (load_cfg().get("default_voice"), "默认音色")):
        if want:
            if want in by:
                return by[want]
            if why != "默认音色":
                raise SystemExit(f"{why} 指定的音色「{want}」不在音色库里。已有：{'、'.join(by) }")
    real = [v for v in lib if v.get("consent") != "demo"]
    return (real or lib)[0]


def _store(src: Path, name: str, text: str, consent: str, who: str, tags: list, style: str) -> Path:
    d = voices_dir() / safe_name(name)
    d.mkdir(parents=True, exist_ok=True)
    wav = d / "prompt.wav"
    # mono 24 kHz, trim leading/trailing silence, level to -20 LUFS: a clean, consistent prompt clones best
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af",
         "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.1,areverse,"
         "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.15,areverse,"
         "highpass=f=70,loudnorm=I=-20:TP=-3:LRA=11", "-ac", "1", "-ar", "24000", str(wav)])
    dur = probe_dur(wav)
    meta = {"name": d.name, "text": text, "consent": consent, "consent_label": CONSENT[consent], "who": who,
            "tags": tags, "style": style, "seconds": round(dur, 2), "source_file": src.name,
            "added": dt.date.today().isoformat()}
    (d / "voice.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return d


def preview(v: dict, text: str = PREVIEW_TEXT) -> Path:
    home, py = cosyvoice()
    if not py.exists():
        raise SystemExit(f"本机 CosyVoice 没装（{home}），先运行 tools/cosyvoice/install.sh 或 install.ps1")
    out = Path(v["dir"]) / "试听.wav"
    r = subprocess.run([str(py), str(REPO / "tools" / "cosyvoice" / "clone_tts.py"), "--prompt", v["prompt"],
                        "--prompt-text", v["text"], "--text", text, "--style", v.get("style") or "none", "--out", str(out)],
                       env={**os.environ, "COSYVOICE_HOME": str(home), "PYTHONIOENCODING": "utf-8"},
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        print(r.stderr[-2000:])
        raise SystemExit("试听生成失败")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("audio")
    p.add_argument("--name", required=True)
    p.add_argument("--text", required=True, help="录音里说的每一个字，必须和录音完全一致")
    p.add_argument("--consent", required=True, choices=list(CONSENT))
    p.add_argument("--who", default="", help="授权人和日期（consent=permission 时必填）")
    p.add_argument("--tags", default="")
    p.add_argument("--style", default="none", choices=["none", "happy", "fast", "loud", "soft"])
    p.add_argument("--default", action="store_true")
    p.add_argument("--preview", action="store_true")
    sub.add_parser("list")
    p = sub.add_parser("default")
    p.add_argument("name")
    p = sub.add_parser("preview")
    p.add_argument("name")
    p.add_argument("--text", default=PREVIEW_TEXT)
    p = sub.add_parser("remove")
    p.add_argument("name")
    a = ap.parse_args()

    if a.cmd == "add":
        src = Path(a.audio).expanduser().resolve()
        if not src.is_file():
            raise SystemExit(f"找不到录音文件：{src}")
        if a.consent == "permission" and not a.who.strip():
            raise SystemExit("别人的声音必须写明授权人和日期：--who \"张三，书面同意 2026-11-09\"")
        text = a.text.strip()
        if len(re.sub(r"[^一-鿿A-Za-z0-9]", "", text)) < 4:
            raise SystemExit("--text 太短：要写出录音里说的每一个字")
        d = _store(src, a.name, text, a.consent, a.who.strip(), [t for t in re.split(r"[,，、\s]+", a.tags) if t], a.style)
        meta = json.loads((d / "voice.json").read_text(encoding="utf-8"))
        warn = []
        if meta["seconds"] < 3:
            shutil.rmtree(d)
            raise SystemExit(f"录音去掉静音后只有 {meta['seconds']} 秒，太短了：需要 5-15 秒的说话")
        if meta["seconds"] > 20:
            warn.append(f"录音 {meta['seconds']} 秒偏长（建议 5-15 秒），克隆会变慢，可以剪短一点")
        n_chars = len(re.sub(r"[^一-鿿]", "", text))
        if n_chars and not 2.0 <= n_chars / meta["seconds"] <= 8.5:
            warn.append(f"文字 {n_chars} 字对 {meta['seconds']} 秒录音，语速不像正常说话：请核对文字是否和录音完全一致")
        if a.default or not load_cfg().get("default_voice"):
            cfg = load_cfg()
            cfg["default_voice"] = meta["name"]
            save_cfg(cfg)
        res = {"added": meta["name"], "seconds": meta["seconds"], "consent": meta["consent_label"],
               "default": load_cfg().get("default_voice"), "dir": str(d), "warnings": warn}
        if a.preview:
            res["preview"] = str(preview({**meta, "dir": str(d), "prompt": str(d / "prompt.wav")}))
        print(json.dumps(res, ensure_ascii=False, indent=1))
    elif a.cmd == "list":
        default = load_cfg().get("default_voice")
        rows = [{"name": v["name"], "default": v["name"] == default, "seconds": v["seconds"], "consent": v["consent_label"],
                 "tags": v.get("tags", []), "style": v.get("style", "none"),
                 "preview": str(Path(v["dir"]) / "试听.wav") if (Path(v["dir"]) / "试听.wav").is_file() else None}
                for v in library()]
        print(json.dumps({"voices_dir": str(voices_dir()), "voices": rows}, ensure_ascii=False, indent=1))
    elif a.cmd == "default":
        v = pick(a.name)
        cfg = load_cfg()
        cfg["default_voice"] = v["name"]
        save_cfg(cfg)
        print(json.dumps({"default_voice": v["name"]}, ensure_ascii=False))
    elif a.cmd == "preview":
        print(json.dumps({"preview": str(preview(pick(a.name), a.text))}, ensure_ascii=False))
    elif a.cmd == "remove":
        v = pick(a.name)
        shutil.rmtree(v["dir"])
        cfg = load_cfg()
        if cfg.get("default_voice") == v["name"]:
            cfg.pop("default_voice")
            save_cfg(cfg)
        print(json.dumps({"removed": v["name"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
