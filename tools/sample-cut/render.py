"""Render a product video to the sample standard (shot rhythm, push-in, grade, action sound, subtitles).

usage (inside the project work dir): python render.py <narration_dir> <out_name>
inputs: copy.json (units -> shot folders), takes/selected-takes.json, <narration_dir>/narration.json + narration.wav, spec.json
output: renders/<out_name>/<out_name>.mp4 (+ edit-plan.json, captions.json/.srt, voice_norm.wav, sfx.wav for make_draft.py)
env: COPY=<other copy file>, CAPTION_STYLE=<name in styles.json> (else copy.json "style", spec subtitle.style, auto)
"""
import json
import os
import re
import sys
from pathlib import Path

import captions
from vw_common import encode_checked, run, work_dir

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

# ---------- 4. captions: style library, keyword highlight, intro animation (captions.py) ----------
st = SPEC["subtitle"]
end_all = total_frames / FPS
STYLE_NAME = captions.pick_style(COPY.get("product", ""), " ".join(x["text"] for x in COPY["sentences"]),
                                 os.environ.get("CAPTION_STYLE") or COPY.get("style") or st.get("style"))
STYLE = captions.STYLES[STYLE_NAME]
_pterms = captions.product_terms(COPY.get("product", "")) + [SPEC.get("cover", {}).get("title", "")]


def _emph(u):  # Codex may list emphasis words per sentence; otherwise pick them deterministically
    given = COPY["sentences"][u["i"]].get("emphasis")
    return [w for w in given if w in u["text"]] if given else captions.emphasis_terms(u["text"], _pterms)


cues = captions.build_cues(units, captions.max_chars_for(STYLE, st.get("max_chars", 15)), end_all, _emph)
(OUT / "captions.json").write_text(json.dumps({"style": STYLE_NAME, "cues": cues}, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
srt = []
for i, c in enumerate(cues, 1):
    f = lambda x: f"{int(x // 3600):02d}:{int(x // 60 % 60):02d}:{int(x % 60):02d},{int(round(x % 1 * 1000)) % 1000:03d}"
    srt += [str(i), f"{f(c['start'])} --> {f(c['end'])}", c["text"], ""]
(OUT / "captions.srt").write_text("\n".join(srt), encoding="utf-8")
cap_list, cap_y = captions.render_layer(cues, STYLE, end_all, FPS, OUT / "caption-frames")

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


n_in = inputs.count("-i")
inputs += ["-f", "concat", "-safe", "0", "-i", str(cap_list)]
vchain = f"[{n_in}:v]fps={FPS},format=rgba[cap];[0:v][cap]overlay=0:{cap_y}:format=auto:eof_action=pass[vo]"
final = OUT / f"{NAME}.mp4"
enc = encode_checked(lambda a: ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", fc + ";" + vchain,
                                "-map", "[vo]", "-map", "[a]", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
                                "-profile:v", "high", "-pix_fmt", "yuv420p", *a, "-ar", "48000",
                                "-movflags", "+faststart", "-t", f"{end_all:.3f}", str(final)], final, bitrate="192k")
print(json.dumps({"final": str(final), "duration": round(end_all, 3), "shots": len(plan),
                  "avg_shot_s": round(end_all / len(plan), 2), "cues": len(cues), "caption_style": STYLE_NAME, **enc}, ensure_ascii=False))
