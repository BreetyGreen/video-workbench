"""Build the narration: synthesize each copy unit, cut breath gaps, join with controlled gaps.

usage (inside the project work dir): python voice_build.py <voice> <speech_rate> [comma_gap_s] [period_gap_s]
cloud DashScope cosyvoice-v2 (needs your own key). Per-unit synthesis; for more natural prosody synthesize the whole
script at once (local CosyVoice: tools/cosyvoice) and run narration_from_whole.py instead.
writes voice/<voice>/narration.wav and narration.json (per-unit start/end, used for shots and subtitles)
"""
import json
import os
import re
import sys
from pathlib import Path

from vw_common import init_dashscope, probe_dur as dur, run, work_dir

init_dashscope()
from dashscope.audio.tts_v2 import SpeechSynthesizer  # noqa: E402

WORK = work_dir()
voice = sys.argv[1]
rate = float(sys.argv[2])
comma_gap = float(sys.argv[3]) if len(sys.argv) > 3 else 0.06
period_gap = float(sys.argv[4]) if len(sys.argv) > 4 else 0.14
SR = 48000
out_dir = WORK / "voice" / (f"{voice}_r{rate}" + ("" if os.environ.get("COPY", "copy.json") == "copy.json" else "_" + Path(os.environ["COPY"]).stem))
out_dir.mkdir(parents=True, exist_ok=True)
COPY_NAME = os.environ.get("COPY", "copy.json")
copy = json.loads((WORK / COPY_NAME).read_text(encoding="utf-8"))


# Breath-gap cut (lesson 气口): drop leading/trailing silence, shrink interior pauses to ~70 ms.
TRIM = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.02,"
        "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.03,areverse,"
        "silenceremove=stop_periods=-1:stop_threshold=-45dB:stop_duration=0.07:stop_silence=0.07")

pieces, units, t = [], [], 0.0
for i, s in enumerate(copy["sentences"]):
    raw = out_dir / f"u{i:02d}.mp3"
    if not raw.exists():
        audio = SpeechSynthesizer(model="cosyvoice-v2", voice=voice, speech_rate=rate).call(s["text"])
        if not audio:
            raise RuntimeError(f"empty audio for unit {i}")
        raw.write_bytes(audio)
    clean = out_dir / f"u{i:02d}.wav"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af", TRIM, "-ar", str(SR), "-ac", "1", str(clean)])
    d = dur(clean)
    units.append({"i": i, "text": s["text"], "part": s["part"], "shots": s["shots"], "start": round(t, 3),
                  "end": round(t + d, 3)})
    pieces.append(clean)
    t += d
    if i < len(copy["sentences"]) - 1:
        gap = period_gap if re.search(r"[。！？!?]$", s["text"]) else comma_gap
        g = out_dir / f"gap{i:02d}.wav"
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=mono", "-t", f"{gap}", str(g)])
        pieces.append(g)
        t += gap

lst = out_dir / "concat.txt"
lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in pieces), encoding="utf-8")
narr = out_dir / "narration.wav"
run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "pcm_s16le", str(narr)])
total = dur(narr)
chars = sum(len(re.sub(r"[^\u4e00-\u9fff0-9A-Za-z]", "", u["text"])) for u in units)
(out_dir / "narration.json").write_text(json.dumps({"voice": voice, "rate": rate, "duration": total, "chars": chars,
                                                    "cps": round(chars / total, 2), "units": units},
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{voice} r{rate}: {total:.2f}s, {chars} chars, {chars / total:.2f} chars/s -> {narr}")
