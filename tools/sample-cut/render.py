"""Render a product video to the sample standard (shot rhythm, push-in, grade, action sound, subtitles).

usage (inside the project work dir): python render.py <narration_dir> <out_name>
inputs: copy.json (units -> shot folders), takes/selected-takes.json, <narration_dir>/narration.json + narration.wav, spec.json
output: renders/<out_name>/<out_name>.mp4 (+ edit-plan.json, captions.srt/.ass, voice_norm.wav, sfx.wav for make_draft.py)
env: COPY=<other copy file>
"""
import json
import math
import os
import re
import sys
from pathlib import Path

from vw_common import encode_checked, fonts_dir, run, subtitle_font, work_dir

WORK = work_dir()
NARR = Path(sys.argv[1]).resolve()
NAME = sys.argv[2]
OUT = WORK / "renders" / NAME
CLIPS = OUT / "clips"
CLIPS.mkdir(parents=True, exist_ok=True)
SPEC = json.loads((WORK / "spec.json").read_text(encoding="utf-8"))
TAKES = json.loads((WORK / "takes" / "selected-takes.json").read_text(encoding="utf-8"))
narr = json.loads((NARR / "narration.json").read_text(encoding="utf-8"))
COPY = json.loads((WORK / os.environ.get("COPY", "copy.json")).read_text(encoding="utf-8"))
for _u in narr["units"]:
    _u["shots"] = COPY["sentences"][_u["i"]]["shots"]  # copy.json is the source of truth for shot mapping
FPS = 30
W, H = 1080, 1920


# ---------- 1. shot plan: cut on unit starts, split long units into ~target-length shots ----------
units = narr["units"]
tail = SPEC["edit"]["tail_after_voice_s"]
spans = []
for k, u in enumerate(units):
    start = 0.0 if k == 0 else u["start"]
    end = units[k + 1]["start"] if k + 1 < len(units) else u["end"] + tail
    spans.append((start, end))

used: dict[str, int] = {}
plan = []
for u, (s, e) in zip(units, spans):
    span = e - s
    n = max(1, round(span / SPEC["edit"]["target_shot_s"]))
    n = max(n, min(len(u["shots"]), int(span // SPEC["edit"]["min_shot_s"]) or 1))
    if all(f in SPEC["edit"].get("single_shot_folders", []) for f in u["shots"]) and span <= SPEC["edit"]["single_shot_max_s"]:
        n = 1
    elif all(f in SPEC["edit"]["long_ok_folders"] for f in u["shots"]) and span / len(u["shots"]) <= SPEC["edit"]["long_ok_max_s"]:
        n = len(u["shots"])
    seg = span / n
    for j in range(n):
        folder = u["shots"][j % len(u["shots"])]
        cands = TAKES[folder]
        idx = used.get(folder, 0)
        used[folder] = idx + 1
        take = cands[idx % len(cands)]
        plan.append({"unit": u["i"], "folder": folder, "take": take, "t0": round(s + j * seg, 3),
                     "dur": round(seg, 3)})

# frame-accurate durations so the concatenated picture matches the narration timeline
acc = 0
for p in plan:
    frames_end = round((p["t0"] + p["dur"]) * FPS)
    p["frames"] = frames_end - acc
    acc = frames_end
total_frames = acc

# ---------- 2. per-shot render: window on the action core, slow-mo if needed, push-in, grade ----------
grade = SPEC["color"]["ffmpeg_filter"]
for n, p in enumerate(plan):
    t = p["take"]
    src = t["file"]
    need = p["frames"] / FPS
    src_len = float(run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration",
                         "-of", "csv=p=0", src]).stdout.strip().splitlines()[0].split(",")[0])
    win_in, win_out = float(t["in"]), float(t["out"])
    core = max(0.2, win_out - win_in)
    # speed < 1 = slow motion (60 fps source keeps it smooth). Only slow down, never speed up actions.
    speed = min(1.0, max(SPEC["edit"]["min_speed"], core / need))
    src_need = need * speed
    mid = (win_in + win_out) / 2
    a = max(0.05, min(mid - src_need / 2, src_len - src_need - 0.05))
    zoom0 = float(t.get("suggest_zoom") or 1.0)
    zoom0 = max(1.0, min(SPEC["edit"]["max_static_zoom"], zoom0))
    zoom0 = max(zoom0, SPEC["edit"].get("min_zoom_by_folder", {}).get(p["folder"], 1.0))
    if p["folder"] in SPEC["edit"]["no_push_folders"]:
        push = 0.0
    elif p["folder"] in SPEC["edit"]["push_strong_folders"]:
        push = SPEC["edit"]["push_strong"]
    else:
        push = SPEC["edit"]["push_in_per_shot"]
    # keep the end scale within the lesson's ~125% ceiling
    push = max(0.0, min(push, 1.3 - zoom0))
    cx, cy = t.get("subject_center") or [0.5, 0.5]
    frames = p["frames"]
    # zoompan on a 2x upscaled frame keeps the push-in smooth (less integer jitter)
    z_expr = f"{zoom0}+{push}*on/{max(1, frames - 1)}"
    x_expr = f"max(0,min(iw-iw/zoom,{cx}*iw-iw/zoom/2))"
    y_expr = f"max(0,min(ih-ih/zoom,{cy}*ih-ih/zoom/2))"
    vf = (f"setpts=(PTS-STARTPTS)/{speed},fps={FPS},scale={W * 2}:{H * 2}:flags=lanczos,"
          f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d=1:s={W}x{H}:fps={FPS},"
          f"{grade},format=yuv420p")
    clip = CLIPS / f"c{n:02d}.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{src_need + 0.2:.3f}", "-i", src,
         "-vf", vf, "-frames:v", str(frames), "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "16", str(clip)])
    # original action sound for the SFX layer (same window and speed; pitch drop on slow-mo is acceptable for SFX)
    sfx = CLIPS / f"s{n:02d}.wav"
    atempo = []
    sp = speed
    while sp < 0.5:
        atempo.append("atempo=0.5")
        sp /= 0.5
    atempo.append(f"atempo={sp:.4f}")
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{src_need + 0.2:.3f}", "-i", src, "-vn",
         "-af", ",".join(atempo) + f",atrim=0:{frames / FPS:.4f},asetpts=PTS-STARTPTS,"
         "aresample=48000,aformat=channel_layouts=mono,apad", "-t", f"{frames / FPS:.4f}", str(sfx)])
    # level the action sound per shot (lesson: action shots keep original sound turned up, others muted)
    au = SPEC["audio"]
    sfx_p = CLIPS / f"p{n:02d}.wav"
    dur_s = frames / FPS
    if p["folder"] in au["sfx_folders"]:
        gated = CLIPS / f"g{n:02d}.wav"
        run(["ffmpeg", "-v", "error", "-y", "-i", str(sfx), "-af",
             f"highpass=f=150,agate=threshold={au['sfx_gate']}:ratio=4:attack=5:release=120", str(gated)])
        st_ = run(["ffmpeg", "-hide_banner", "-i", str(gated), "-af", "astats=metadata=0", "-f", "null", "-"]).stderr
        rms_v = re.findall(r"RMS level dB: (-inf|[-0-9.]+)", st_)
        rms = float(rms_v[-1]) if rms_v and rms_v[-1] != "-inf" else -90.0
        gain = max(-20.0, min(18.0, au["sfx_target_rms_db"] - rms)) if rms > -70 else -60.0
        run(["ffmpeg", "-v", "error", "-y", "-i", str(gated), "-af",
             f"volume={gain:.2f}dB,alimiter=limit={au['sfx_peak_limit']}:attack=2:release=50:level=disabled,"
             f"afade=t=in:d=0.015,afade=t=out:st={max(0, dur_s - 0.03):.3f}:d=0.03", "-ar", "48000", str(sfx_p)])
        p["sfx_gain_db"] = round(gain, 1)
    else:
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", f"{dur_s:.4f}", str(sfx_p)])
        p["sfx_gain_db"] = None
    p.update({"src_in": round(a, 3), "src_len": round(src_need, 3), "speed": round(speed, 3), "zoom0": zoom0,
              "push": push, "clip": clip.name})

(OUT / "edit-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")

# ---------- 3. concat picture + SFX bed ----------
(OUT / "v.txt").write_text("".join(f"file '{(CLIPS / p['clip']).as_posix()}'\n" for p in plan), encoding="utf-8")
(OUT / "s.txt").write_text("".join(f"file '{(CLIPS / ('p' + p['clip'][1:3] + '.wav')).as_posix()}'\n" for p in plan),
                           encoding="utf-8")
picture = OUT / "picture.mp4"
run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(OUT / "v.txt"), "-c", "copy", str(picture)])
sfxbed = OUT / "sfx.wav"
run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(OUT / "s.txt"), "-c", "pcm_s16le", str(sfxbed)])

# ---------- 4. subtitles (ASS) ----------
st = SPEC["subtitle"]


def ass_time(x):
    cs = int(round(x * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


cues = []
for u in units:
    parts = [x for x in re.split(r"[，。！？、,!?]", u["text"]) if x.strip()]
    # merge or split to keep each cue within max chars
    chunks = []
    for x in parts:
        while len(x) > st["max_chars"]:
            cut = math.ceil(len(x) / math.ceil(len(x) / st["max_chars"]))
            chunks.append(x[:cut])
            x = x[cut:]
        chunks.append(x)
    total_c = sum(len(c) for c in chunks)
    t = u["start"]
    for c in chunks:
        d = (u["end"] - u["start"]) * len(c) / total_c
        cues.append((t, t + d, c))
        t += d
# hold each cue until the next one starts (no flicker in short gaps); last ends with the video
end_all = total_frames / FPS
cues = [(s, (cues[i + 1][0] if i + 1 < len(cues) else min(e + 0.3, end_all - 0.05)), c) for i, (s, e, c) in enumerate(cues)]
ass = [
    "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "",
    "[V4+ Styles]",
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
    "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    f"Style: Main,{subtitle_font(st['font'])},{st['size']},{st['primary']},&H000000FF,{st['outline_colour']},{st['back_colour']},"
    f"{-1 if st['bold'] else 0},0,0,0,100,100,{st['spacing']},0,1,{st['outline']},{st['shadow']},8,60,60,{st['margin_v']},1",
    "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
]
for s, e, c in cues:
    ass.append(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},Main,,0,0,0,,{c}")
(OUT / "captions.ass").write_text("\n".join(ass) + "\n", encoding="utf-8-sig")
srt = []
for i, (s, e, c) in enumerate(cues, 1):
    f = lambda x: f"{int(x // 3600):02d}:{int(x // 60 % 60):02d}:{int(x % 60):02d},{int(round(x % 1 * 1000)) % 1000:03d}"
    srt += [str(i), f"{f(s)} --> {f(e)}", c, ""]
(OUT / "captions.srt").write_text("\n".join(srt), encoding="utf-8")

# ---------- 5. mix: voice + gated original action sound (+ optional BGM) ----------
mix = SPEC["audio"]
# voice normalised to a fixed level so the per-shot SFX targets are relative to it (same files go into the Jianying draft)
_err = run(["ffmpeg", "-hide_banner", "-i", str(NARR / "narration.wav"), "-af", "loudnorm=print_format=json", "-f", "null", "-"]).stderr
_vin = float(json.loads(_err[_err.rfind("{"):_err.rfind("}") + 1])["input_i"])
voice_norm = OUT / "voice_norm.wav"
run(["ffmpeg", "-v", "error", "-y", "-i", str(NARR / "narration.wav"), "-af",
     f"aresample=48000,highpass=f=70,acompressor=threshold=-20dB:ratio=3:attack=5:release=80,"
     f"volume={mix['voice_lufs'] - _vin:.2f}dB,alimiter=limit=0.89:level=disabled,apad",
     "-t", f"{end_all:.3f}", str(voice_norm)])
inputs = ["-i", str(picture), "-i", str(voice_norm), "-i", str(sfxbed)]
fc = "[1:a]anull[v];[2:a]anull[s];"
bgm = mix.get("bgm_file")
if bgm:
    inputs += ["-stream_loop", "-1", "-i", bgm]
    fc += (f"[3:a]aresample=48000,volume={mix['bgm_gain_db']}dB[b0];"
           f"[b0][v]sidechaincompress=threshold=0.05:ratio=6:attack=20:release=300[b];"
           f"[v][s][b]amix=inputs=3:normalize=0:duration=first[m];")
else:
    fc += "[v][s]amix=inputs=2:normalize=0:duration=first[m];"
# loudnorm alone overshoots after AAC (measured -0.3..-0.7 dBTP); a 4x-oversampled limiter at -2 dBFS keeps TP < -1.5
fc += (f"[m]loudnorm=I={mix['target_lufs']}:TP=-1.5:LRA=11,aresample=192000,"
       f"alimiter=limit=0.79:level=false:attack=1:release=50,aresample=48000,atrim=0:{end_all:.3f}[a]")
def esc(p: str) -> str:  # ffmpeg filter-arg escaping for paths (drive colon, quotes)
    return p.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


fdir = fonts_dir()
ass_f = f"ass='{esc((OUT / 'captions.ass').as_posix())}'" + (f":fontsdir='{esc(fdir)}'" if fdir else "")
final = OUT / f"{NAME}.mp4"
enc = encode_checked(lambda a: ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", fc + f";[0:v]{ass_f}[vo]",
                                "-map", "[vo]", "-map", "[a]", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
                                "-profile:v", "high", "-pix_fmt", "yuv420p", *a, "-ar", "48000",
                                "-movflags", "+faststart", "-t", f"{end_all:.3f}", str(final)], final, bitrate="192k")
print(json.dumps({"final": str(final), "duration": round(end_all, 3), "shots": len(plan),
                  "avg_shot_s": round(end_all / len(plan), 2), "cues": len(cues), **enc}, ensure_ascii=False))
