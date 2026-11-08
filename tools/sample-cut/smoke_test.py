"""End-to-end smoke test on synthetic media (no real footage, no key, no network).

usage: uv run --project tools/sample-cut python tools/sample-cut/smoke_test.py [out_dir]
Builds a tiny project (3 shot folders with Chinese names, synthetic narration and bright BGM), then runs
make_sheets + scan_materials -> render (styled captions) -> add_bgm -> qa -> make_draft --dry-run and checks
loudness, true peak, encoder, captions in every style family and the QA gate.
Writes <out_dir>/smoke-frame.png (frame with burned-in Chinese subtitle) for a visual check.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from vw_common import IS_MAC, IS_WIN, integrated_lufs, is_bold, pil_font, run, true_peak  # noqa: E402

out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="sample-cut-smoke-")).resolve()
work = out_dir / "work"
mats = out_dir / "素材"
for p in (work / "takes", work / "voice" / "synth", mats):
    p.mkdir(parents=True, exist_ok=True)

folders = ["1.倒水", "2.展示一杯", "3.配料表"]
takes = {}
for k, f in enumerate(folders):
    (mats / f).mkdir(exist_ok=True)
    clip = mats / f / f"clip{k}.mp4"
    if not clip.exists():
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=1080x1920:rate=30",
             "-f", "lavfi", "-i", f"sine=f={300 + 200 * k}:sample_rate=48000", "-t", "3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", clip])
    takes[f] = [{"file": str(clip), "rank": 1, "in": 0.4, "out": 2.2, "subject_center": [0.5, 0.5], "suggest_zoom": 1.1}]
(work / "takes" / "selected-takes.json").write_text(json.dumps(takes, ensure_ascii=False), encoding="utf-8")

sentences = [{"part": "开头", "text": "冰冰凉凉倒一杯，", "shots": [folders[0]]},
             {"part": "卖点", "text": "零糖零脂零能量。", "shots": [folders[2]]},
             {"part": "结尾", "text": "喜欢的宝子点左下角！", "shots": [folders[1]]}]
(work / "copy.json").write_text(json.dumps({"product": "冒烟测试", "facts_from_package": [], "not_claimed": [],
                                            "sentences": sentences}, ensure_ascii=False), encoding="utf-8")
spec = json.loads((HERE / "examples" / "spec.json").read_text(encoding="utf-8"))
e = spec["edit"]
e.update(push_strong_folders=[folders[0]], no_push_folders=[folders[2]], single_shot_folders=[folders[2]],
         long_ok_folders=[folders[0], folders[2]], min_zoom_by_folder={folders[0]: 1.15})
spec["audio"]["sfx_folders"] = [folders[0]]
(work / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

# synthetic "voice": amplitude-modulated tone, 3 units over 4.5 s
narr = work / "voice" / "synth" / "narration.wav"
run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:sample_rate=48000", "-af",
     "volume='0.5+0.4*sin(2*PI*3*t)':eval=frame", "-t", "4.5", "-ac", "1", narr])
units = [{"i": i, "text": s["text"], "part": s["part"], "shots": s["shots"], "start": 1.5 * i, "end": 1.5 * i + 1.4}
         for i, s in enumerate(sentences)]
(narr.parent / "narration.json").write_text(json.dumps({"units": units}, ensure_ascii=False), encoding="utf-8")

# bright, loud BGM: the case where ffmpeg's native aac overshot +3 dBTP
bgm_dir = out_dir / "bgm" / "tracks"
bgm_dir.mkdir(parents=True, exist_ok=True)
bgm = bgm_dir / "Bright Test.mp3"
run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=color=white:amplitude=0.6:sample_rate=48000",
     "-f", "lavfi", "-i", "sine=f=3500:sample_rate=48000", "-filter_complex",
     "[0:a][1:a]amix=inputs=2:normalize=0,highpass=f=2000,volume=4,aformat=channel_layouts=stereo", "-t", "12",
     "-c:a", "libmp3lame", "-b:a", "192k", bgm])

env = {**os.environ, "SAMPLE_CUT_WORK": str(work), "PYTHONIOENCODING": "utf-8"}


def step(script, *args):
    r = subprocess.run([sys.executable, str(HERE / script), *map(str, args)], env=env, cwd=work,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(f"--- {script}: exit {r.returncode}\n{r.stdout.strip()[-600:]}")
    if r.returncode:
        print(r.stderr[-2000:])
        raise SystemExit(f"{script} failed")
    return r.stdout.strip().splitlines()[-1]


step("make_sheets.py", mats)
step("scan_materials.py", mats)
assert len(json.loads((work / "takes" / "clips.json").read_text(encoding="utf-8"))) == 3, "scan_materials"
assert len(list((work / "takes" / "thumbs").glob("*__*.jpg"))) == 15, "thumbnails missing"
res = json.loads(step("render.py", narr.parent, "smoke"))
final = Path(res["final"])
res_bgm = json.loads(step("add_bgm.py", final, bgm, work / "renders" / "smoke" / "smoke-bgm.mp4"))
step("qa.py", "smoke", work / "renders" / "smoke" / "smoke-bgm.mp4")
step("make_draft.py", "smoke", "冒烟测试", "--bgm", bgm, "--dry-run")

expect_enc = "aac_at" if IS_MAC else "aac_mf" if IS_WIN else "aac"
checks = {
    "render_encoder": res["encoder"] == expect_enc,
    "bgm_encoder": res_bgm["encoder"] == expect_enc,
    "render_tp<=-1.5": true_peak(final) <= -1.5,
    "bgm_tp<=-1.5": true_peak(res_bgm["out"]) <= -1.5,
    "bgm_lufs~-14": abs(integrated_lufs(res_bgm["out"]) + 14) <= 1.0,
    "duration": abs(res["duration"] - (4.4 + spec["edit"]["tail_after_voice_s"])) < 0.1,
}

# subtitle burned in: compare the caption band of the final frame with the subtitle-free picture
frame = out_dir / "smoke-frame.png"
run(["ffmpeg", "-v", "error", "-y", "-ss", "2.0", "-i", final, "-frames:v", "1", "-update", "1", frame])
import captions  # noqa: E402

band = f"crop=1080:220:0:{int(captions.STYLES[res['caption_style']]['y'] * 1920) - 40}"


def band_bytes(src):
    return subprocess.run(["ffmpeg", "-v", "error", "-ss", "2.0", "-i", str(src), "-frames:v", "1", "-vf",
                           band + ",format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout


a, b = band_bytes(final), band_bytes(work / "renders" / "smoke" / "picture.mp4")
diff = sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a))
checks["subtitle_drawn"] = diff > 3.0
sub_font = pil_font(48, bold=True)
if IS_MAC or IS_WIN:
    checks["fallback_font_bold"] = is_bold(sub_font)  # used when fonts_download.py has not run
# every style must draw (fonts present or fallback) without error and produce visible ink
for name, st_ in captions.STYLES.items():
    img, _ = captions.draw_line("零糖零脂冰冰凉凉", [(0, 2)], st_)
    checks[f"style_{name}"] = img.getbbox() is not None
print(json.dumps({"caption_style": res["caption_style"], "encoder": res["encoder"], "true_peak": res["true_peak"], "bgm_true_peak": res_bgm["true_peak"],
                  "subtitle_band_diff": round(diff, 2), "pillow_font": list(sub_font.getname()), "frame": str(frame), "checks": checks}, ensure_ascii=False, indent=1))
if not all(checks.values()):
    raise SystemExit("smoke test FAILED: " + ", ".join(k for k, v in checks.items() if not v))
print("smoke test passed")
