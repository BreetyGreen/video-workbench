"""Preset voice library for the local voice (CosyVoice zero-shot clone). No cloud, no key.

usage (uv run --project tools/sample-cut python tools/sample-cut/voices.py ...):
  add <audio> --name 女声活泼 --text "录音里的每一个字" --consent own|permission [--who "张三，书面同意 2026-11-09"]
      [--tags 女声,活泼] [--style none|happy] [--default] [--preview]
  list                     the library as JSON
  default <name>           voice used when a video doesn't name one
  preview <name> [--text]  synthesize a short sample -> <voice dir>/试听.wav (takes a few minutes on CPU)
  remove <name>            delete one preset (only the copy in the library; the original recording is untouched)
  pack [--preview]         install the built-in voice pack (voice_pack.json): adult speakers from the AISHELL-3
                           corpus (Apache-2.0, recorded for multi-speaker TTS); no recording needed
  match                    which voice the current project (copy.json in the work dir) gets, and why

Each preset is <voices dir>/<name>/prompt.wav (5-15 s, mono 24 kHz, levelled, silence trimmed) + voice.json.
voices dir: VIDEO_WORKBENCH_VOICES_DIR, else <data_home>/voices.

Consent is required for every preset: "own" = the user's own voice, "permission" = a person who gave written
permission (record who/when in --who), "licensed" = a speaker of an openly licensed TTS corpus (set by `pack` only;
the source and license are stored in voice.json). "demo" is reserved for CosyVoice's bundled sample (tests only).

Automatic matching (no --voice-name, no copy.json "voice", no default_voice): the product's mood (styles.json
mood_keywords) is scored against each voice's gender / age / pitch tags; a stable hash of the product name picks
among the best few, so the same product always gets the same voice and different products vary.
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

CONSENT = {"own": "本人的声音", "permission": "已获本人书面授权", "licensed": "开放授权语音库 AISHELL-3（Apache-2.0）",
           "demo": "CosyVoice 官方示例（仅演示）"}
PACK = HERE / "voice_pack.json"
# product mood -> wanted voice tags, most important first (tags come from the corpus metadata and measured pitch)
MOOD_VOICE = {
    "茶": ["成熟", "中音", "低音", "女声"], "健康": ["女声", "成熟", "中音"], "饮品": ["青年", "女声", "高音", "中音"],
    "甜品": ["女声", "青年", "高音"], "零食": ["青年", "高音", "男声"], "辣味": ["男声", "青年", "中音"],
    "母婴": ["女声", "成熟", "低音", "中音"], "日用": ["女声", "成熟", "中音"], "通用": ["女声", "青年", "中音"],
}
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


def match(copy: dict | None, lib: list[dict]) -> tuple[dict, str]:
    """Voice for this product by mood: score tags, then a stable hash picks among the best few."""
    copy = copy or {}
    product = copy.get("product", "")
    blob = product + "".join(s.get("text", "") for s in copy.get("sentences", []))
    kws = json.loads((HERE / "styles.json").read_text(encoding="utf-8"))["mood_keywords"]
    moods = [m for m, ks in kws.items() if any(k in blob for k in ks)] or ["通用"]
    want: dict[str, float] = {}
    for m in moods:
        for i, tag in enumerate(MOOD_VOICE.get(m, MOOD_VOICE["通用"])):
            want[tag] = want.get(tag, 0) + 4 - min(i, 3)
    real = [v for v in lib if v.get("consent") != "demo"] or lib
    own = [v for v in real if v.get("consent") in ("own", "permission")]
    pool = own or real  # voices the user added themself come before the built-in pack
    score = lambda v: sum(w for tag, w in want.items() if tag in v.get("tags", []))
    ranked = sorted(pool, key=lambda v: (-score(v), v["name"]))
    best = [v for v in ranked if score(v) >= score(ranked[0]) - 1][:4]
    v = best[sum(map(ord, product)) % len(best)]
    hit = "、".join(tag for tag in v.get("tags", []) if tag in want) or "默认"
    return v, f"按「{'、'.join(moods)}」类产品自动匹配（{hit}）"


def pick(name: str | None = None, copy: dict | None = None) -> dict | None:
    """Explicit name > copy.json "voice" > default_voice in settings > automatic match. None = empty library.
    The returned dict carries "why" (how it was chosen)."""
    lib = library()
    if not lib:
        return None
    by = {v["name"]: v for v in lib}
    for want, why in ((name, "--voice-name"), ((copy or {}).get("voice"), 'copy.json "voice"'),
                      (load_cfg().get("default_voice"), "默认音色")):
        if want:
            if want in by:
                return {**by[want], "why": why}
            if why != "默认音色":
                raise SystemExit(f"{why} 指定的音色「{want}」不在音色库里。已有：{'、'.join(by) }")
    v, why = match(copy, lib)
    return {**v, "why": why}


def _store(src: Path, name: str, text: str, consent: str, who: str, tags: list, style: str,
           extra: dict | None = None) -> Path:
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
            "added": dt.date.today().isoformat(), **(extra or {})}
    (d / "voice.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return d


def install_pack(force: bool = False) -> dict:
    """Download the pack's clips (a few hundred KB each), verify sha256, register them as presets. Idempotent."""
    import hashlib
    import urllib.request

    pack = json.loads(PACK.read_text(encoding="utf-8"))
    cache = voices_dir() / ".pack-cache"
    cache.mkdir(parents=True, exist_ok=True)
    done, failed = [], []
    for v in pack["voices"]:
        d = voices_dir() / safe_name(v["name"])
        if (d / "voice.json").is_file() and (d / "prompt.wav").is_file() and not force:
            done.append(v["name"])
            continue
        raw = cache / v["file"]
        ok = raw.is_file() and hashlib.sha256(raw.read_bytes()).hexdigest() == v["sha256"]
        err = ""
        for base in ([] if ok else pack["mirrors"]):
            try:
                req = urllib.request.Request(f"{base}/{v['speaker']}/{v['file']}", headers={"User-Agent": "video-workbench"})
                data = urllib.request.urlopen(req, timeout=60).read()
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                continue
            if hashlib.sha256(data).hexdigest() == v["sha256"]:
                raw.write_bytes(data)
                ok = True
                break
            err = "sha256 mismatch"
        if not ok:
            failed.append(f"{v['name']}（{err}）")
            continue
        _store(raw, v["name"], v["text"], "licensed", "", v["tags"], v.get("style", pack.get("style", "none")),
               {"source": pack["source"], "license": pack["license"], "speaker": v["speaker"], "median_f0": v.get("f0")})
        done.append(v["name"])
    return {"installed": len(done), "failed": failed, "voices_dir": str(voices_dir())}


def preview_many(vs: list[dict], text: str = PREVIEW_TEXT) -> list[Path]:
    """Previews for several voices with one model load."""
    home, py = cosyvoice()
    if not py.exists():
        raise SystemExit(f"本机 CosyVoice 没装（{home}），先运行 tools/cosyvoice/install.sh 或 install.ps1")
    jobs = [{"prompt": v["prompt"], "prompt_text": v["text"], "text": text, "style": v.get("style") or "none",
             "out": str(Path(v["dir"]) / "试听.wav")} for v in vs]
    jf = voices_dir() / ".preview-jobs.json"
    jf.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([str(py), str(REPO / "tools" / "cosyvoice" / "clone_tts.py"), "--jobs", str(jf)],
                       env={**os.environ, "COSYVOICE_HOME": str(home), "PYTHONIOENCODING": "utf-8"},
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    jf.unlink(missing_ok=True)
    if r.returncode:
        print(r.stderr[-2000:])
        raise SystemExit("试听生成失败")
    return [Path(j["out"]) for j in jobs]


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
    p.add_argument("--consent", required=True, choices=["own", "permission", "demo"])
    p.add_argument("--who", default="", help="授权人和日期（consent=permission 时必填）")
    p.add_argument("--tags", default="")
    p.add_argument("--style", default="none", choices=["none", "sales", "happy", "fast", "loud", "soft"])
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
    p = sub.add_parser("pack")
    p.add_argument("--preview", action="store_true", help="also synthesize 试听.wav for every pack voice (slow on CPU)")
    p.add_argument("--force", action="store_true")
    sub.add_parser("match")
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
        if a.default:  # without a default, each product gets the best-matching voice
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
        rows = [{"name": v["name"], "default": v["name"] == default, "seconds": v["seconds"],
                 "consent": CONSENT.get(v.get("consent"), v.get("consent_label")),
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
    elif a.cmd == "pack":
        res = install_pack(a.force)
        if a.preview:
            todo = [v for v in library() if v.get("consent") == "licensed" and not (Path(v["dir"]) / "试听.wav").is_file()]
            res["previews"] = len(preview_many(todo)) if todo else 0
        print(json.dumps(res, ensure_ascii=False, indent=1))
        sys.exit(1 if res["failed"] and not res["installed"] else 0)
    elif a.cmd == "match":
        from vw_common import work_dir
        cp = work_dir() / "copy.json"
        v = pick(None, json.loads(cp.read_text(encoding="utf-8")) if cp.is_file() else None)
        print(json.dumps({"voice": v and v["name"], "why": v and v["why"], "tags": v and v.get("tags")}, ensure_ascii=False))
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
