"""Score every library track by how much of it a phone speaker can actually play.

usage: python bgm_analyze.py    (writes "phone_db" into <library>/manifest.json; produce.py runs it when missing)
phone_db = RMS of the 300 Hz-6 kHz band minus full-band RMS, over the first 40 s. Phone speakers reproduce little
below ~250 Hz, so a bass/drum groove (Wallpaper: -9.9 dB) sounds almost silent on a phone even at the same
loudness, while melody tracks (Water Droplets on the River: -1.2 dB) come through clearly.
"""
import json
import os
import re
import subprocess
from pathlib import Path

from vw_common import data_home

LIB = Path(os.environ.get("VIDEO_WORKBENCH_BGM_DIR") or data_home() / "bgm-library" / "incompetech")
PHONE_MIN_DB = -6.0  # tracks below this are skipped by produce.py


def rms(path: Path, extra: str = "") -> float:
    af = f"atrim=0:40,{extra + ',' if extra else ''}astats=measure_overall=RMS_level:measure_perchannel=none"
    e = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", af, "-f", "null", "-"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace").stderr
    vals = re.findall(r"RMS level dB: (-?[\d.]+)", e)
    return float(vals[-1]) if vals else -99.0


def analyze(force: bool = False) -> list:
    man_path = LIB / "manifest.json"
    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    changed = False
    for m in manifest:
        t = LIB / "tracks" / Path(m["file"]).name
        if t.is_file() and (force or "phone_db" not in m):
            m["phone_db"] = round(rms(t, "highpass=f=300,lowpass=f=6000") - rms(t), 1)
            changed = True
    if changed:
        man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    for m in sorted(analyze(force=True), key=lambda m: -m.get("phone_db", -99)):
        flag = "" if m.get("phone_db", -99) >= PHONE_MIN_DB else "  (skipped: mostly bass, inaudible on phones)"
        print(f"{m.get('phone_db', '?'):>6} dB  {m['title']}{flag}")
