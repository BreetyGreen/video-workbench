"""Pick light, upbeat instrumental tracks from the Incompetech catalog for product videos (CC BY 4.0).

usage: python bgm_pick.py [count=30]   -> <library>/picked.json, then run bgm_download.py
library: VIDEO_WORKBENCH_BGM_DIR, default <data_home>/bgm-library/incompetech (see vw_common.data_home)
"""
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

from vw_common import data_home

LIB = Path(os.environ.get("VIDEO_WORKBENCH_BGM_DIR") or data_home() / "bgm-library" / "incompetech")
LIB.mkdir(parents=True, exist_ok=True)
cat_path = LIB / "pieces.json"
if not cat_path.exists():
    cat_path.write_bytes(urllib.request.urlopen("https://incompetech.com/music/royalty-free/pieces.json", timeout=60).read())
cat = json.loads(cat_path.read_text(encoding="utf-8"))

GOOD = {"bright": 3, "uplifting": 3, "happy": 3, "playful": 2, "bouncy": 2, "light": 2, "relaxed": 1, "calming": 1,
        "carefree": 3, "cheerful": 3, "funky": 1, "groovy": 1, "fun": 2, "quirky": 1, "positive": 2, "sunny": 2}
BAD = ["dark", "epic", "mysterious", "horror", "action", "medieval", "ren faire", "tense", "suspense", "somber",
       "sad", "aggressive", "unnerving", "eerie", "ominous", "christmas", "holiday", "march", "military", "heavy"]
NICE_INST = ["ukulele", "acoustic guitar", "guitar", "piano", "bells", "glockenspiel", "marimba", "whistle",
             "claps", "pizzicato", "xylophone", "kalimba", "electric piano"]


def secs(t):
    p = [int(x) for x in t.split(":")]
    return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]


rows = []
for t in cat:
    feel = (t.get("feel") or "").lower()
    desc = (t.get("description") or "").lower()
    inst = (t.get("instruments") or "").lower()
    if any(b in feel or b in desc for b in BAD):
        continue
    if re.search(r"\bvocal|\bvoice|\bsinging|\bchoir|crumhorn|lute", inst):
        continue
    if re.search(r"jingle|noel|christmas|merry|santa|xmas", t["title"].lower()):
        continue
    try:
        L, bpm = secs(t["length"]), int(t.get("bpm") or 0)
    except ValueError:
        continue
    if not (60 <= L <= 300) or not (88 <= bpm <= 145):
        continue
    score = sum(w for k, w in GOOD.items() if k in feel) + sum(1 for k in NICE_INST if k in inst)
    if score < 4:
        continue
    rows.append({"title": t["title"], "filename": t["filename"], "length": t["length"], "bpm": bpm,
                 "feel": t.get("feel"), "instruments": t.get("instruments"), "score": score})
rows.sort(key=lambda r: (-r["score"], r["title"]))
n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
pick = rows[:n]
(LIB / "picked.json").write_text(json.dumps(pick, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(rows), "candidates;", len(pick), "picked")
for r in pick:
    print(f"{r['score']:2d} {r['bpm']:3d}bpm {r['length']}  {r['title']}  | {r['feel']} | {r['instruments']}")
