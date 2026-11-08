"""Autopilot step 1: index every clip under a materials folder (any layout) and make numbered contact sheets.

usage (inside the project work dir): python scan_materials.py <materials_dir> [--per-sheet 8]
writes takes/clips.json  {"c001": {"file", "dur", "fps", "folder", "times"}, ...}
       takes/sheets/sheet-01.jpg ...  (each column = one clip, labelled with its id; 4 frames down, time-stamped)
       takes/sheet-index.json
Sheets are small on purpose (token cost): look at them, then open single frames only when unsure
(ffmpeg -ss <t> -i <file> -frames:v 1 frame.jpg).
"""
import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw

from vw_common import pil_font, work_dir

ap = argparse.ArgumentParser()
ap.add_argument("materials")
ap.add_argument("--per-sheet", type=int, default=8)
a = ap.parse_args()
SRC = Path(a.materials).resolve()
OUT = work_dir() / "takes"
SHEETS, THUMBS = OUT / "sheets", OUT / "thumbs"
for p in (SHEETS, THUMBS):
    p.mkdir(parents=True, exist_ok=True)
FR = [0.1, 0.38, 0.66, 0.92]
TW, TH = 136, 242
EXT = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".mts"}
font, small = pil_font(20, bold=True), pil_font(15)


def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=duration,avg_frame_rate:format=duration", "-of", "json", str(p)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    j = json.loads(r.stdout or "{}")
    s = (j.get("streams") or [{}])[0]
    n, d = (s.get("avg_frame_rate") or "0/1").split("/")
    dur = float(s.get("duration") or j.get("format", {}).get("duration") or 0)
    return dur, float(n) / float(d or 1)


def thumb(args):
    p, t, out = args
    if out.exists():
        return None
    vf = (f"scale={TW}:{TH}:force_original_aspect_ratio=decrease,crop='min(iw,{TW})':'min(ih,{TH})',"
          f"pad={TW}:{TH}:(ow-iw)/2:(oh-ih)/2")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(p), "-frames:v", "1", "-vf", vf,
                        "-update", "1", str(out)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return None if r.returncode == 0 and out.exists() else f"{p.name}@{t}: {r.stderr.strip()[-160:]}"


files = sorted(p for p in SRC.rglob("*") if p.suffix.lower() in EXT and p.is_file() and not p.name.startswith("."))
if not files:
    raise SystemExit(f"no video clips found under {SRC}")
clips, jobs = {}, []
for k, f in enumerate(files, 1):
    cid = f"c{k:03d}"
    dur, fps = probe(f)
    if dur < 0.5:
        continue
    times = [round(x * dur, 2) for x in FR]
    tf = [THUMBS / f"{cid}_{j}.jpg" for j in range(len(FR))]
    clips[cid] = {"file": str(f), "dur": round(dur, 2), "fps": round(fps, 2),
                  "folder": str(f.parent.relative_to(SRC)) if f.parent != SRC else "", "times": times,
                  "thumbs": [str(x) for x in tf]}
    jobs += [(f, t, o) for t, o in zip(times, tf)]
with ThreadPoolExecutor(8) as ex:
    errors = [e for e in ex.map(thumb, jobs) if e]

ids, index = list(clips), {}
for s in range(0, len(ids), a.per_sheet):
    group = ids[s:s + a.per_sheet]
    img = Image.new("RGB", (TW * len(group), 52 + TH * len(FR)), "white")
    dr = ImageDraw.Draw(img)
    for ci, cid in enumerate(group):
        c = clips[cid]
        dr.text((ci * TW + 4, 2), cid, fill="black", font=font)
        dr.text((ci * TW + 4, 28), f"{c['dur']:.1f}s {c['folder'][:7]}", fill=(90, 90, 90), font=small)
        for j, (t, tp) in enumerate(zip(c["times"], c["thumbs"])):
            y = 52 + j * TH
            if Path(tp).exists():
                img.paste(Image.open(tp), (ci * TW, y))
            dr.rectangle([ci * TW + 2, y + 2, ci * TW + 54, y + 22], fill="black")
            dr.text((ci * TW + 5, y + 3), f"{t:.1f}", fill="yellow", font=small)
        dr.line([(ci * TW, 0), (ci * TW, img.height)], fill=(180, 180, 180))
    path = SHEETS / f"sheet-{s // a.per_sheet + 1:02d}.jpg"
    img.save(path, quality=80)
    index[path.name] = group
(OUT / "clips.json").write_text(json.dumps(clips, ensure_ascii=False, indent=1), encoding="utf-8")
(OUT / "sheet-index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
if errors:
    print(f"{len(errors)} thumbnails failed, first: {errors[0]}", file=sys.stderr)
print(json.dumps({"clips": len(clips), "sheets": len(index), "thumb_errors": len(errors),
                  "folders": sorted({c["folder"] for c in clips.values()})[:30]}, ensure_ascii=False))
