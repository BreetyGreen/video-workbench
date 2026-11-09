"""Turn a whole-script voice file (natural prosody, e.g. local CosyVoice3) into a render-ready narration dir.

usage (inside the project work dir): python narration_from_whole.py <voice.wav> <out_dir> [target_cps=6.8]
with a DashScope key: ASR word timestamps (paraformer-realtime-v2) give exact unit timings; without one the units
are placed by character share and snapped to the nearest detected pause (good enough for cuts and captions)
1. cut breath gaps (interior pauses -> ~90 ms), 2. atempo to the target speaking rate (pitch kept),
3. ASR word timestamps -> align to copy.json characters -> per-unit start/end, 4. write narration.wav/json
"""
import difflib
import json
import os
import re
import sys
from pathlib import Path

from vw_common import init_dashscope, probe_dur as dur, run, work_dir

try:
    init_dashscope()
    from dashscope.audio.asr import Recognition
    HAVE_ASR = True
except SystemExit:  # no key: fall back to pause-snapped proportional timing
    HAVE_ASR = False

WORK = work_dir()

src, out = Path(sys.argv[1]), Path(sys.argv[2])
target_cps = float(sys.argv[3]) if len(sys.argv) > 3 else 6.8
out.mkdir(parents=True, exist_ok=True)
copy = json.loads((WORK / os.environ.get("COPY", "copy.json")).read_text(encoding="utf-8"))
keep = lambda s: re.sub(r"[^\u4e00-\u9fff0-9A-Za-z]", "", s)
chars = sum(len(keep(s["text"])) for s in copy["sentences"])


TRIM = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.03,"
        "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,"
        "silenceremove=stop_periods=-1:stop_threshold=-42dB:stop_duration=0.09:stop_silence=0.09")
trimmed = out / "trimmed.wav"
run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", TRIM, "-ar", "48000", "-ac", "1", str(trimmed)])
d_trim = dur(trimmed)
tempo = max(1.0, min(1.45, target_cps * d_trim / chars))
narr = out / "narration.wav"
run(["ffmpeg", "-v", "error", "-y", "-i", str(trimmed), "-af", f"atempo={tempo:.4f}", "-ar", "48000", "-ac", "1",
     "-c:a", "pcm_s16le", str(narr)])
total = dur(narr)

orig = "".join(keep(s["text"]) for s in copy["sentences"])
transcript, matched = "", None
if HAVE_ASR:
    # ---- ASR word timestamps on the final audio ----
    asr16 = out / "asr16k.wav"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(narr), "-ac", "1", "-ar", "16000", str(asr16)])
    res = Recognition(model="paraformer-realtime-v2", format="wav", sample_rate=16000, callback=None).call(str(asr16))
    asr_chars, asr_t = [], []  # one entry per recognised character: (begin_s, end_s)
    for sent in res.get_sentence() or []:
        for w in sent.get("words", []):
            t = keep(w.get("text", ""))
            if not t:
                continue
            b, e = w["begin_time"] / 1000, w["end_time"] / 1000
            step = (e - b) / len(t)
            for k, ch in enumerate(t):
                asr_chars.append(ch)
                asr_t.append((b + k * step, b + (k + 1) * step))
    transcript = "".join(asr_chars)

    times: list = [None] * len(orig)
    for a, b, n in difflib.SequenceMatcher(None, orig, transcript, autojunk=False).get_matching_blocks():
        for k in range(n):
            times[a + k] = asr_t[b + k]
    matched = sum(t is not None for t in times)


    def at(i, edge):  # nearest matched char time, interpolated by index when unmatched
        if times[i] is not None:
            return times[i][edge]
        lo = next((j for j in range(i, -1, -1) if times[j] is not None), None)
        hi = next((j for j in range(i, len(times)) if times[j] is not None), None)
        if lo is None:
            return times[hi][0]
        if hi is None:
            return times[lo][1]
        f = (i - lo) / (hi - lo)
        return times[lo][1] + f * (times[hi][0] - times[lo][1])


else:
    # pauses in the trimmed voice: sentence boundaries sit in them
    st_ = run(["ffmpeg", "-hide_banner", "-i", str(narr), "-af", "silencedetect=n=-40dB:d=0.06", "-f", "null", "-"]).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", st_)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", st_)]
    pauses = [(a0 + b0) / 2 for a0, b0 in zip(starts, ends)]
    times = []
    for k in range(len(orig)):
        t0, t1 = total * k / len(orig), total * (k + 1) / len(orig)
        times.append((t0, t1))

    def at(i, edge):  # proportional time of character i
        return times[i][edge]

    def snap(t):
        near = min(pauses, key=lambda x: abs(x - t), default=None)
        return near if near is not None and abs(near - t) <= 0.35 else t

units, pos = [], 0
for i, s in enumerate(copy["sentences"]):
    n = len(keep(s["text"]))
    st, en = at(pos, 0), at(pos + n - 1, 1)
    if not HAVE_ASR:
        st, en = (0.0 if i == 0 else snap(st)), (total if i == len(copy["sentences"]) - 1 else snap(en))
    units.append({"i": i, "text": s["text"], "part": s["part"], "shots": s["shots"],
                  "start": round(max(0.0, st - 0.04), 3), "end": round(min(total, en + 0.04), 3)})
    pos += n
units[0]["start"] = 0.0
for k in range(1, len(units)):  # keep monotonic
    units[k]["start"] = max(units[k]["start"], units[k - 1]["start"] + 0.3)
meta = {"voice": src.stem, "engine": os.environ.get("VOICE_ENGINE", "local-cosyvoice3"), "rate": round(tempo, 3), "duration": round(total, 3),
        "chars": chars, "cps": round(chars / total, 2), "asr_char_match": round(matched / len(orig), 3) if matched is not None else None,
        "timing": "asr" if HAVE_ASR else "proportional+pauses",
        "asr_transcript": transcript, "units": units}
(out / "narration.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({k: v for k, v in meta.items() if k not in ("units", "asr_transcript")}, ensure_ascii=False))
for u in units:
    print(f"{u['start']:6.2f}-{u['end']:6.2f} {u['text']}")
