"""Autopilot step 2: read the package text (front, ingredient list, side claims) from clips with OCR.

usage (inside the project work dir): python ocr_text.py c012 c013 c047 ...   (clip ids from takes/clips.json)
Samples 3 frames per clip (plus a sharpened 2x copy for small print), keeps lines with confidence >= 0.8,
merges duplicates, and writes takes/ocr.json. Copy facts must come only from these lines.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from vw_common import work_dir

WORK = work_dir()
clips = json.loads((WORK / "takes" / "clips.json").read_text(encoding="utf-8"))
ids = [x for x in sys.argv[1:] if x in clips]
if not ids:
    raise SystemExit("give clip ids from takes/clips.json, e.g. python ocr_text.py c012 c047")
from rapidocr import RapidOCR  # noqa: E402  (slow import; after argument checks)

ocr = RapidOCR()
tmp = Path(tempfile.mkdtemp(prefix="ocr-"))
seen: dict[str, dict] = {}
for cid in ids:
    c = clips[cid]
    for k, f in enumerate((0.3, 0.55, 0.8)):
        img = tmp / f"{cid}_{k}.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{c['dur'] * f:.2f}", "-i", c["file"], "-frames:v", "1",
                        "-vf", "scale=iw*2:ih*2:flags=lanczos,unsharp=5:5:0.8", "-update", "1", str(img)],
                       capture_output=True)
        if not img.exists():
            continue
        r = ocr(str(img))
        for t, s in zip(r.txts or [], r.scores or []):
            t = "".join(t.split())
            if float(s) < 0.8 or len(t) < 2:
                continue
            row = seen.setdefault(t, {"text": t, "score": 0.0, "clips": []})
            row["score"] = max(row["score"], round(float(s), 3))
            if cid not in row["clips"]:
                row["clips"].append(cid)
lines = sorted(seen.values(), key=lambda r: (-len(r["clips"]), -r["score"]))
# drop lines fully contained in a longer, equally confident line
lines = [r for r in lines if not any(r["text"] != o["text"] and r["text"] in o["text"] and o["score"] >= r["score"]
                                     for o in lines)]
out = WORK / "takes" / "ocr.json"
prev = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
merged = {r["text"]: r for r in [*prev, *lines]}
out.write_text(json.dumps(list(merged.values()), ensure_ascii=False, indent=1), encoding="utf-8")
for r in lines:
    print(f"{r['score']:.2f} {','.join(r['clips'])}  {r['text']}")
print(f"-> {out} ({len(merged)} lines)")
