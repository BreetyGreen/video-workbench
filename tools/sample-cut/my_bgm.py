"""Your own BGM folder ("我的BGM"): drop music files in, produce.py uses them before the built-in CC BY library.

usage: python my_bgm.py            scan the folder and print every track with its phone score
folder: VIDEO_WORKBENCH_MY_BGM_DIR, else "my_bgm_dir" in sample-cut.json,
        else ~/Movies/VideoWorkbench 我的BGM (macOS) or <repo>/data/我的BGM (Windows)
Supported: mp3 m4a aac wav flac ogg. Optional credit line per track: a text file with the same name
(<track>.txt), its first line goes into 发布文案.txt (needed by e.g. Uppbeat free tracks; Pixabay/Mixkit need none).
Each track gets phone_db (see bgm_analyze.py): below -6 dB it is mostly bass and nearly silent on a phone speaker,
so those are used only when nothing better is in the folder. Results are cached in <folder>/.analysis.json.
The user is responsible for having the right to use the music they put here (see 先看这里.md).
"""
import json
import os
from pathlib import Path

from vw_common import IS_MAC, REPO, data_home, probe_dur

EXTS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg"}
README = """把你想用的 BGM 放进这个文件夹（mp3 / m4a / wav / flac 都可以），下次做视频会优先用这里的曲子。

- 每条视频会从这里挑最多 3 首，各做一个版本：一个当成片，其余放进 BGM备选/。
- 程序会先测一下每首曲子在手机外放时能不能听清。以低音鼓点为主的曲子手机上几乎听不见，有更好的曲子时会被跳过。
- 曲子需要署名的（比如 Uppbeat 免费曲），在旁边放一个同名的 .txt 文件，第一行写署名，会自动加进 发布文案.txt。
- 只放你有权使用的音乐：Pixabay Music、Mixkit、Uppbeat、你买过授权的曲子等。抖音热门音乐请在抖音发布时直接选，
  用交付文件夹里的「无BGM版」上传即可。
"""


def folder() -> Path:
    cfg_p = data_home() / "sample-cut.json"
    cfg = json.loads(cfg_p.read_text(encoding="utf-8")) if cfg_p.is_file() else {}
    d = os.environ.get("VIDEO_WORKBENCH_MY_BGM_DIR") or cfg.get("my_bgm_dir")
    if d:
        return Path(d).expanduser()
    return Path.home() / "Movies" / "VideoWorkbench 我的BGM" if IS_MAC else REPO / "data" / "我的BGM"


def ensure_folder() -> Path:
    d = folder()
    d.mkdir(parents=True, exist_ok=True)
    readme = d / "说明.txt"
    if not readme.exists():
        readme.write_text(README, encoding="utf-8")
    return d


def scan() -> list[dict]:
    d = folder()
    if not d.is_dir():
        return []
    files = sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in EXTS and not p.name.startswith("."))
    cache_p = d / ".analysis.json"
    try:
        cache = json.loads(cache_p.read_text(encoding="utf-8")) if cache_p.is_file() else {}
    except ValueError:
        cache = {}
    from bgm_analyze import rms

    out, fresh = [], {}
    for p in files:
        st = p.stat()
        key = f"{p.name}|{st.st_size}|{int(st.st_mtime)}"
        row = cache.get(key)
        if not row:
            try:
                row = {"phone_db": round(rms(p, "highpass=f=300,lowpass=f=6000") - rms(p), 1),
                       "seconds": round(probe_dur(p), 1)}
            except Exception as e:  # unreadable file: report, don't stop the video
                row = {"error": str(e)[:200]}
        fresh[key] = row
        if "error" in row:
            continue
        credit_p = p.with_suffix(".txt")
        credit = credit_p.read_text(encoding="utf-8").strip().splitlines()[0].strip() if credit_p.is_file() else ""
        out.append({"title": p.stem, "path": str(p), "credit": credit or None, "source": "我的BGM", **row})
    if fresh != cache:
        try:
            cache_p.write_text(json.dumps(fresh, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
    return out


if __name__ == "__main__":
    ensure_folder()
    rows = scan()
    print(json.dumps({"folder": str(folder()), "tracks": [
        {k: r[k] for k in ("title", "phone_db", "seconds", "credit")} | (
            {"note": "以低音为主，手机外放可能听不清"} if r["phone_db"] < -6 else {}) for r in rows]},
        ensure_ascii=False, indent=1))
