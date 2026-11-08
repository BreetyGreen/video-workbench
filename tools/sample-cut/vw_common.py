"""Shared helpers for the sample-standard cut tools (Windows + macOS).

Every tool works on a *project work dir* (spec.json, copy.json, takes/, voice/, renders/).
It is the current directory, or SAMPLE_CUT_WORK when set.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"


def work_dir() -> Path:
    return Path(os.environ.get("SAMPLE_CUT_WORK") or os.getcwd()).resolve()


def data_home() -> Path:
    """User-owned data (BGM library, CosyVoice). Never inside git-tracked paths."""
    if os.environ.get("VIDEO_WORKBENCH_DATA_DIR"):
        return Path(os.environ["VIDEO_WORKBENCH_DATA_DIR"]).expanduser()
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "VideoWorkbench"
    return REPO / "data"


def run(args, tail: int = 1500) -> subprocess.CompletedProcess:
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise RuntimeError(" ".join(map(str, args))[:300] + "\n" + r.stderr[-tail:])
    return r


_FILTERS: set[str] | None = None


def has_filter(name: str) -> bool:
    """Homebrew's default `ffmpeg` formula ships without libass (no `ass`/`subtitles` filters); ffmpeg-full has them."""
    global _FILTERS
    if _FILTERS is None:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
        _FILTERS = {ln.split()[1] for ln in out.splitlines() if len(ln.split()) > 2 and ln.startswith(" ")}
    return name in _FILTERS


def ffmpeg_reason(text: str) -> str:
    """The line that explains an ffmpeg failure; its last line is usually just 'Invalid argument'."""
    keys = ("No such filter", "Unknown encoder", "Unrecognized option", "not found", "No such file", "Invalid data",
            "Error initializing", "Error opening")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for k in keys:
        for ln in lines:
            if k in ln:
                return ln[:200]
    return (lines[-1] if lines else "unknown error")[:200]


def probe_dur(p) -> float:
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]).stdout)


# ---------- DashScope key (cloud TTS / ASR) ----------

def dashscope_key() -> str:
    """Process env first. Windows may fall back to the ignored repo .env; macOS never reads .env (AGENTS.md).
    VIDEO_WORKBENCH_OFFLINE=1 forces the no-key path (tests, or to keep everything on the machine)."""
    if os.environ.get("VIDEO_WORKBENCH_OFFLINE") == "1":
        raise SystemExit("VIDEO_WORKBENCH_OFFLINE=1: cloud voice/ASR disabled")
    for k in ("VIDEO_WORKBENCH_DASHSCOPE_API_KEY", "DASHSCOPE_API_KEY"):
        if os.environ.get(k):
            return os.environ[k]
    env_file = REPO / ".env"
    if not IS_MAC and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^(VIDEO_WORKBENCH_DASHSCOPE_API_KEY|DASHSCOPE_API_KEY)=(.*)$", line.strip())
            if m and m.group(2).strip().strip('"'):
                return m.group(2).strip().strip('"')
    raise SystemExit("缺少阿里云百炼 Key：请在终端里先 export VIDEO_WORKBENCH_DASHSCOPE_API_KEY=你自己的Key 再运行。"
                     "（只有云端配音/语音识别需要；本机 CosyVoice 配音和剪辑不需要）")


def init_dashscope():
    import dashscope
    dashscope.api_key = dashscope_key()
    return dashscope


# ---------- audio encoding with a true-peak guard ----------

def aac_encoders() -> list[list[str]]:
    """ffmpeg's native aac overshot to +3..+4 dBTP on bright music even after a -2 dB limiter.
    Use the OS encoder first (AudioToolbox on macOS, MediaFoundation on Windows), native aac last."""
    first = [["aac_at", "-aac_at_mode", "cbr"]] if IS_MAC else [["aac_mf"]] if IS_WIN else []
    return first + [["aac"]]


def true_peak(path) -> float:
    e = run(["ffmpeg", "-hide_banner", "-i", path, "-af", "ebur128=peak=true:framelog=quiet", "-f", "null", "-"]).stderr
    return float(e.rsplit("Peak:", 1)[1].split("dBFS")[0])


def integrated_lufs(path) -> float:
    e = run(["ffmpeg", "-hide_banner", "-i", path, "-af", "ebur128=framelog=quiet", "-f", "null", "-"]).stderr
    return float(e.rsplit(" I:", 1)[1].split("LUFS")[0])


def encode_checked(build, out, bitrate: str = "256k", max_tp: float = -1.0) -> dict:
    """build(audio_codec_args) -> full ffmpeg argv writing `out`. Tries encoders until true peak <= max_tp."""
    tried = []
    for enc in aac_encoders():
        try:
            run(build(["-c:a", enc[0], *enc[1:], "-b:a", bitrate]))
        except RuntimeError as e:
            tried.append(f"{enc[0]}: failed ({ffmpeg_reason(str(e))})")
            continue
        tp = true_peak(out)
        tried.append(f"{enc[0]}: {tp} dBTP")
        if tp <= max_tp:
            return {"encoder": enc[0], "true_peak": tp}
    raise SystemExit(f"音频真峰值超标（{'; '.join(tried)}），请检查 {out}")


# ---------- fonts ----------

MAC_FONT_FOR = {"Microsoft YaHei": "PingFang SC", "微软雅黑": "PingFang SC", "SimHei": "Heiti SC"}


def subtitle_font(name: str) -> str:
    return MAC_FONT_FOR.get(name, name) if IS_MAC else name


def fonts_dir() -> str | None:
    """libass fontsdir. Windows needs it; on macOS libass finds system fonts through CoreText."""
    if IS_WIN:
        return os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    return None


BOLD_STYLES = ("heavy", "black", "bold", "semibold", "demibold", "w6", "w7", "w8", "medium")


def is_bold(font) -> bool:
    try:
        return any(b in font.getname()[1].lower() for b in BOLD_STYLES[:-1])
    except Exception:
        return False


def _faces(path: Path, size: int):
    """All faces of a font file; .ttc collections (PingFang, Hiragino) hold several weights."""
    from PIL import ImageFont
    for i in range(64):
        try:
            f = ImageFont.truetype(str(path), size, index=i)
        except OSError:
            return
        yield f
        if path.suffix.lower() != ".ttc":
            return


def pil_font(size: int, bold: bool = False):
    """CJK-capable font for Pillow. With bold=True pick the boldest Simplified-Chinese face a collection offers
    (index 0 of PingFang.ttc / Hiragino Sans GB.ttc is a regular weight)."""
    from PIL import ImageFont
    if IS_WIN:
        names = ["msyhbd.ttc", "msyh.ttc", "arialbd.ttf", "arial.ttf"] if bold else ["msyh.ttc", "arial.ttf"]
        paths = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / n for n in names]
    else:
        paths = [Path(c) for c in ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc",
                                   "/System/Library/Fonts/STHeiti Medium.ttc", "/System/Library/Fonts/Helvetica.ttc",
                                   "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                                   "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                                   "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    for p in paths:
        if not p.is_file():
            continue
        faces = list(_faces(p, size))
        if not faces:
            continue

        def score(f):
            fam, style = (x.lower() for x in f.getname())
            weight = next((len(BOLD_STYLES) - k for k, b in enumerate(BOLD_STYLES) if b in style), 0)
            sc = 2 if (" sc" in fam or "gb" in fam or "yahei" in fam) else 0
            return (weight if bold else -weight) * 3 + sc

        return max(faces, key=score)
    return ImageFont.load_default(size)


# ---------- Jianying (剪映) locations ----------

def jianying_paths() -> tuple[Path, Path]:
    """(draft_root, root_meta_info.json). Override with JIANYING_DRAFT_ROOT / JIANYING_DRAFT_INDEX."""
    home = Path.home()
    if IS_MAC:
        roots = [home / "Movies" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft",
                 home / "Library" / "Application Support" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft"]
    else:
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        roots = [local / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft"]
    default_root = next((r for r in roots if r.is_dir()), roots[0])
    root = Path(os.environ["JIANYING_DRAFT_ROOT"]) if os.environ.get("JIANYING_DRAFT_ROOT") else default_root
    # Windows keeps the index in LOCALAPPDATA even when the draft folder was moved to another drive
    index = Path(os.environ["JIANYING_DRAFT_INDEX"]) if os.environ.get("JIANYING_DRAFT_INDEX") else (
        default_root / "root_meta_info.json")
    return root, index


def jianying_running() -> bool:
    if IS_WIN:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq JianyingPro.exe", "/NH"], capture_output=True, text=True)
        return "JianyingPro.exe" in r.stdout
    r = subprocess.run(["pgrep", "-if", "JianyingPro|VideoFusion"], capture_output=True, text=True)
    return bool(r.stdout.strip())


def load_json(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))
