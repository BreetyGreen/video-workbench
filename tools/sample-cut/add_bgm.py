"""Mix a licensed BGM bed under a finished video (lesson rule: BGM ~1/10 of the voice, light instrumental).

usage: python add_bgm.py <video.mp4> <bgm.mp3> <out.mp4> [bgm_lufs=-25] [skip_s=auto]
<bgm.mp3> may also be just a track title from the library, e.g. "Carefree"
- BGM normalised to bgm_lufs; after ducking the bed measures ~20 dB under the voice track (= Jianying volume ~10%, the lesson rule). -31 measured 25 dB under: inaudible on a phone
- extra ducking while anyone speaks (sidechain on the video's own audio), 0.4 s fade in, 1.2 s fade out
- final -14 LUFS, oversampled limiter so true peak stays < -1.5 dBTP; video stream copied untouched
- encoder: ffmpeg native aac overshot to +3..+4 dBTP on bright BGM (Carefree) even with a -2 dB limiter, so the OS
  encoder goes first (aac_at on macOS, aac_mf on Windows), native aac last; true peak is re-measured (fails if > -1 dBTP)
writes <out>.credit.txt with the attribution line when the track is in a manifest.json
"""
import json
import os
import sys
from pathlib import Path

from vw_common import data_home, encode_checked, probe_dur, run

video, bgm, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
if not bgm.is_file():  # allow a bare title from the library
    lib = Path(os.environ.get("VIDEO_WORKBENCH_BGM_DIR") or data_home() / "bgm-library" / "incompetech")
    bgm = lib / "tracks" / (bgm.name if bgm.suffix == ".mp3" else bgm.name + ".mp3")
    if not bgm.is_file():
        raise SystemExit(f"BGM not found: {sys.argv[2]} (run bgm_pick.py + bgm_download.py first)")
bgm_lufs = float(sys.argv[4]) if len(sys.argv) > 4 else -25.0

dur = probe_dur(video)
if len(sys.argv) > 5:
    skip = float(sys.argv[5])
else:  # skip a quiet intro: first moment the track gets within 12 dB of its loud parts
    st = run(["ffmpeg", "-hide_banner", "-i", bgm, "-af", "silencedetect=n=-30dB:d=0.3", "-f", "null", "-"]).stderr
    skip = 0.0
    for line in st.splitlines():
        if "silence_end" in line:
            t = float(line.split("silence_end:")[1].split("|")[0])
            if t < 8:
                skip = t
            break
fade_out_at = max(0.0, dur - 1.2)
fc = (f"[1:a]atrim={skip:.3f}:{skip + dur + 1:.3f},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo,"
      f"loudnorm=I={bgm_lufs}:TP=-6:LRA=7,afade=t=in:d=0.4,afade=t=out:st={fade_out_at:.3f}:d=1.2[bg];"
      f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit[main][key];"
      f"[bg][key]sidechaincompress=threshold=0.04:ratio=3:attack=25:release=350:makeup=1[bgd];"
      f"[main][bgd]amix=inputs=2:normalize=0:duration=first,loudnorm=I=-14:TP=-1.5:LRA=11,"
      f"aresample=192000,alimiter=limit=0.79:level=false:attack=1:release=50,aresample=48000[a]")
out.parent.mkdir(parents=True, exist_ok=True)
enc = encode_checked(lambda a: ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(bgm), "-filter_complex", fc,
                                "-map", "0:v", "-map", "[a]", "-c:v", "copy", *a, "-movflags", "+faststart",
                                "-t", f"{dur:.3f}", str(out)], out)
m = bgm.parent.parent / "manifest.json"
credit = None
if m.exists():
    for row in json.loads(m.read_text(encoding="utf-8")):
        if Path(row["file"]).name == bgm.name:
            credit = row["attribution"]
if credit:
    Path(str(out) + ".credit.txt").write_text("发布时把这一行放进作品文案（CC BY 4.0 署名要求）：\n" + credit + "\n", encoding="utf-8")
print(json.dumps({"out": str(out), "bgm": bgm.name, "skip_s": round(skip, 2), **enc, "credit": credit}, ensure_ascii=False))
