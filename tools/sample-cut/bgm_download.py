"""Download picked.json tracks from incompetech.com (sequential, polite) and write a license manifest.

usage: python bgm_download.py   (re-run to retry failures; existing files are skipped)
"""
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

from vw_common import data_home

LIB = Path(os.environ.get("VIDEO_WORKBENCH_BGM_DIR") or data_home() / "bgm-library" / "incompetech")
LIB.mkdir(parents=True, exist_ok=True)
TR = LIB / "tracks"
TR.mkdir(exist_ok=True)
BASE = "https://incompetech.com/music/royalty-free/mp3-royaltyfree/"
picked = json.loads((LIB / "picked.json").read_text(encoding="utf-8"))
manifest = []
for r in picked:
    url = BASE + urllib.parse.quote(r["filename"])
    dst = TR / r["filename"]
    status = "exists"
    if not dst.exists() or dst.stat().st_size < 100_000:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "video-workbench-bgm/1.0"})
            data = urllib.request.urlopen(req, timeout=120).read()
            assert data[:3] == b"ID3" or data[:2] == b"\xff\xfb" or data[:2] == b"\xff\xf3", "not an mp3"
            dst.write_bytes(data)
            status = "downloaded"
            time.sleep(1.5)
        except Exception as e:
            status = f"failed: {e}"
    manifest.append({**r, "file": str(dst), "source_url": url,
                     "license": "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)",
                     "attribution": f'"{r["title"]}" Kevin MacLeod (incompetech.com) Licensed under Creative Commons: By Attribution 4.0 License',
                     "status": status, "bytes": dst.stat().st_size if dst.exists() else 0})
    print(status, r["title"])
(LIB / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
ok = [m for m in manifest if m["bytes"] > 100_000]
print(f"{len(ok)}/{len(manifest)} ok, {sum(m['bytes'] for m in ok) / 1e6:.0f} MB")
