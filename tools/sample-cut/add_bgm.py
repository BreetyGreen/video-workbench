"""Mix a licensed BGM bed under a finished video (lesson rule: BGM ~1/10 of the voice, light instrumental).

usage: python add_bgm.py <video.mp4> <bgm.mp3> <out.mp4> [bgm_lufs=-20] [skip_s=auto]
<bgm.mp3> may also be just a track title from the library, e.g. "Carefree"
- BGM normalised to bgm_lufs and ducked gently (~3 dB) under speech: at -20 the bed sits ~8-10 dB under the voice
  in the phone band (300 Hz-6 kHz) while someone talks. Listening tests on a phone: 25, 17 and 13 dB under were all
  'can't hear the BGM'. The first version (-25 with ratio-3 ducking from -28 dBFS) measured ~19-20 dB under during speech and
  was inaudible on phone speakers.
- bass below 180 Hz removed before levelling (phone speakers can't play it; it only ate the loudness budget)
- gentle ducking while anyone speaks (sidechain on the video's own audio), 0.4 s fade in, 1.2 s fade out
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
bgm_lufs = float(sys.argv[4]) if len(sys.argv) > 4 else -20.0

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
need = skip + dur + 1
looped = None
if probe_dur(bgm) < need:  # a track shorter than the video: loop it into a temp file first
    # (-stream_loop straight into this graph ends the music early once sidechaincompress is involved)
    looped = out.parent / f".loop-{out.stem}.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-v", "error", "-y", "-stream_loop", "-1", "-i", str(bgm), "-t", f"{need + 0.5:.3f}",
         "-ar", "48000", "-ac", "2", str(looped)])
fade_out_at = max(0.0, dur - 1.2)
fc = (f"[1:a]atrim={skip:.3f}:{skip + dur + 1:.3f},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo,"
      # phones barely reproduce < ~200 Hz: drop that bass first so the loudness target lands on the audible melody
      # loudnorm outputs 192 kHz and holds ~3 s of look-ahead: back to 48 kHz, and pad the sidechain key so the
      # compressor doesn't stop when the voice track ends (before this fix the music cut out ~3 s before the end)
      f"highpass=f=180:poles=2,loudnorm=I={bgm_lufs}:TP=-6:LRA=7,aresample=48000,"
      f"afade=t=in:d=0.4,afade=t=out:st={fade_out_at:.3f}:d=1.2[bg];"
      f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit[main][k0];[k0]apad=pad_dur=6[key];"
      f"[bg][key]sidechaincompress=threshold=0.1:ratio=2:attack=40:release=450:makeup=1[bgd];"
      f"[main][bgd]amix=inputs=2:normalize=0:duration=first,loudnorm=I=-14:TP=-1.5:LRA=11,"
      f"aresample=192000,alimiter=limit=0.79:level=false:attack=1:release=50,aresample=48000[a]")
out.parent.mkdir(parents=True, exist_ok=True)
enc = encode_checked(lambda a: ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(looped or bgm),
                                "-filter_complex", fc,
                                "-map", "0:v", "-map", "[a]", "-c:v", "copy", *a, "-movflags", "+faststart",
                                "-t", f"{dur:.3f}", str(out)], out)
if looped:
    looped.unlink(missing_ok=True)
m = bgm.parent.parent / "manifest.json"
credit = None
if m.exists():
    for row in json.loads(m.read_text(encoding="utf-8")):
        if Path(row["file"]).name == bgm.name:
            credit = row["attribution"]
if credit:
    Path(str(out) + ".credit.txt").write_text("发布时把这一行放进作品文案（CC BY 4.0 署名要求）：\n" + credit + "\n", encoding="utf-8")
print(json.dumps({"out": str(out), "bgm": bgm.name, "skip_s": round(skip, 2), **enc, "credit": credit}, ensure_ascii=False))
