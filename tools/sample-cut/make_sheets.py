"""Contact sheets for take selection: per shot folder, 10 clips per sheet, 5 time-labelled frames per clip.

usage (inside the project work dir): python make_sheets.py <materials_dir>
<materials_dir> holds numbered shot folders ("13.倒水", "5.配料表", ...) with .mov/.mp4 clips.
writes takes/sheets/*.jpg, takes/takes-meta.json, takes/sheet-index.json
Then look at the sheets (or ask Codex to) and write takes/selected-takes.json - see README.md.
"""
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw

from vw_common import pil_font, work_dir

SRC = Path(sys.argv[1]).resolve()
OUT = work_dir() / "takes"
SHEETS = OUT / "sheets"
THUMBS = OUT / "thumbs"
SHEETS.mkdir(parents=True, exist_ok=True)
THUMBS.mkdir(parents=True, exist_ok=True)
FR = [0.08, 0.3, 0.5, 0.7, 0.92]
TW, TH, PER = 150, 266, 10  # even size: mjpeg chroma subsampling
font = pil_font(18)


def folder_key(d: Path):
    head = d.name.split(".")[0]
    return (0, int(head), d.name) if head.isdigit() else (1, 0, d.name)


def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=duration,avg_frame_rate", "-of", "json", str(p)], capture_output=True, text=True)
    s = json.loads(r.stdout)["streams"][0]
    n, d = s["avg_frame_rate"].split("/")
    return float(s["duration"]), float(n) / float(d or 1)


def thumb(args):
    p, t, out = args
    if out.exists():
        return None
    # scale can round 1 px over the box (rotated phone clips); crop before pad or pad fails and nothing is written
    vf = (f"scale={TW}:{TH}:force_original_aspect_ratio=decrease,crop='min(iw,{TW})':'min(ih,{TH})',"
          f"pad={TW}:{TH}:(ow-iw)/2:(oh-ih)/2")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(p), "-frames:v", "1", "-vf", vf,
                        "-update", "1", str(out)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return None if r.returncode == 0 and out.exists() else f"{p.name}@{t}: {r.stderr.strip()[-200:]}"


meta, index, jobs = {}, {}, []
for folder in sorted((d for d in SRC.iterdir() if d.is_dir()), key=folder_key):
    clips = sorted([*folder.glob("*.mov"), *folder.glob("*.MOV"), *folder.glob("*.mp4"), *folder.glob("*.MP4")])
    clips = sorted(set(clips))
    meta[folder.name] = []
    for c in clips:
        dur, fps = probe(c)
        times = [round(f * dur, 2) for f in FR]
        tf = [THUMBS / f"{folder.name}__{c.stem}_{k}.jpg" for k in range(len(FR))]
        meta[folder.name].append({"file": str(c), "name": c.name, "dur": round(dur, 3), "fps": round(fps, 2),
                                  "times": times, "thumbs": [str(x) for x in tf]})
        jobs += [(c, t, o) for t, o in zip(times, tf)]
with ThreadPoolExecutor(8) as ex:
    errors = [e for e in ex.map(thumb, jobs) if e]
if errors:
    print(f"{len(errors)} thumbnails failed, first: {errors[0]}", file=sys.stderr)
    if len(errors) == len(jobs):
        raise SystemExit("no thumbnail could be made - check ffmpeg and the materials folder")

for folder, clips in meta.items():
    for s in range(0, len(clips), PER):
        group = clips[s:s + PER]
        img = Image.new("RGB", (TW * len(group), 30 + TH * len(FR)), "white")
        dr = ImageDraw.Draw(img)
        for ci, c in enumerate(group):
            dr.text((ci * TW + 4, 5), Path(c["name"]).stem[-6:] + f" {c['dur']:.1f}s", fill="black", font=font)
            for k, (t, tp) in enumerate(zip(c["times"], c["thumbs"])):
                y = 30 + k * TH
                if Path(tp).exists():
                    img.paste(Image.open(tp), (ci * TW, y))
                dr.rectangle([ci * TW + 2, y + 2, ci * TW + 62, y + 24], fill="black")
                dr.text((ci * TW + 5, y + 3), f"{t:.2f}", fill="yellow", font=font)
        path = SHEETS / f"{folder}_{s // PER + 1}.jpg"
        img.save(path, quality=82)
        index[str(path)] = [c["name"] for c in group]
(OUT / "takes-meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
(OUT / "sheet-index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(index), "sheets,", sum(len(v) for v in meta.values()), "clips,", len(errors), "thumbnail errors")
