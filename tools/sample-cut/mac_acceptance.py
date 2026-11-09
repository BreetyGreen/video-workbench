"""Full end-to-end acceptance on a clean machine (built for GitHub's macOS runners, works anywhere).

usage: uv run --project tools/sample-cut python tools/sample-cut/mac_acceptance.py <out_dir> [--voice local|cloud]
Synthetic footage (no private material leaves the user's machine) + a real 12-sentence copy -> make_spec ->
copy_check -> produce.py (real voice, fonts, BGM library, captions, QA, cover, previews, delivery report).
Needs: autopilot_setup.py done (fonts + BGM); for --voice local an installed CosyVoice (COSYVOICE_HOME).
Exit code = produce.py's (0 pass, 2 QA hard fail).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from vw_common import run  # noqa: E402

out = Path(sys.argv[1]).resolve()
voice = sys.argv[sys.argv.index("--voice") + 1] if "--voice" in sys.argv else "local"
work, mats = out / "work", out / "footage"
for p in (work / "takes", mats):
    p.mkdir(parents=True, exist_ok=True)

# one synthetic clip per shot type: distinct pattern/colour, a tone as "action sound"
types = {"倒水": "testsrc2", "开盖": "smptehdbars", "产品正面": "rgbtestsrc", "产品细节": "testsrc",
         "配料表": "yuvtestsrc", "制作过程": "mandelbrot", "成品展示": "cellauto", "品尝": "life",
         "多件陈列": "pal100bars"}
takes = {}
for k, (t, src) in enumerate(types.items()):
    clip = mats / f"{k + 1:02d}-{t}.mp4"
    if not clip.exists():
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"{src}=size=1080x1920:rate=30" if src not in
             ("cellauto", "life") else f"{src}=size=540x960:rate=30", "-f", "lavfi", "-i",
             f"sine=f={220 + 70 * k}:sample_rate=48000", "-t", "4", "-vf", "scale=1080:1920,format=yuv420p",
             "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-shortest", str(clip)])
    takes[t] = [{"file": str(clip), "rank": 1, "in": 0.6, "out": 2.6, "subject_center": [0.5, 0.5],
                 "suggest_zoom": 1.08, "why": "synthetic acceptance clip"}]
(work / "takes" / "selected-takes.json").write_text(json.dumps(takes, ensure_ascii=False, indent=1), encoding="utf-8")

copy = {
    "product": "一茶 茉莉白牡丹（无糖茶饮料）",
    "facts_from_package": ["无糖", "0糖 0脂肪 0能量", "净含量450mL", "政和白茶（白牡丹）", "茉莉花露", "原叶萃取",
                           "口感顺滑", "同系列：韵香乌龙"],
    "not_claimed": ["价格", "库存", "功效", "与其他品牌比较"],
    "sentences": [
        {"part": "钩子", "text": "喝腻了甜饮料，又想喝点有味道的宝子，", "shots": ["倒水"]},
        {"part": "钩子", "text": "一定要试试这瓶无糖的茉莉白牡丹。", "shots": ["成品展示", "制作过程"]},
        {"part": "产品", "text": "一茶茉莉白牡丹，", "shots": ["产品正面"]},
        {"part": "卖点", "text": "零糖零脂零能量，", "shots": ["配料表"]},
        {"part": "卖点", "text": "用的是政和白牡丹，还加了茉莉花露，", "shots": ["开盖", "产品细节"]},
        {"part": "卖点", "text": "原叶萃取，入口顺滑，茶香清清爽爽。", "shots": ["品尝", "产品细节"]},
        {"part": "喝法", "text": "冰镇后倒进加了冰块的杯子里，", "shots": ["倒水"]},
        {"part": "喝法", "text": "吸管一放，搅一搅，冰冰凉凉。", "shots": ["制作过程"]},
        {"part": "场景", "text": "上班、健身、追剧，来一瓶刚刚好。", "shots": ["成品展示", "品尝"]},
        {"part": "系列", "text": "还有韵香乌龙可以换着喝，", "shots": ["多件陈列"]},
        {"part": "囤货", "text": "冰箱里常备一箱，想喝随时拿，", "shots": ["多件陈列", "产品正面"]},
        {"part": "行动", "text": "喜欢的宝子，点左下角带一箱回家！", "shots": ["产品正面", "成品展示"]},
    ],
}
(work / "copy.json").write_text(json.dumps(copy, ensure_ascii=False, indent=1), encoding="utf-8")
(work / "notes.md").write_text("- 验收用合成画面（不含任何真实素材），只验证声音、字幕、BGM、质检和交付流程。\n", encoding="utf-8")

env = {**os.environ, "SAMPLE_CUT_WORK": str(work), "VIDEO_WORKBENCH_DELIVERIES_DIR": str(out / "delivery"),
       "VIDEO_WORKBENCH_VOICES_DIR": str(out / "voices"), "VIDEO_WORKBENCH_MY_BGM_DIR": str(out / "my-bgm"),
       "PYTHONIOENCODING": "utf-8"}
os.environ.update(env)
from vw_common import data_home  # noqa: E402

# "我的BGM": a melody track cut to 15 s (must loop under the 24 s video, with a credit file) + the most bass-heavy
# library track (must be skipped as inaudible on phones)
lib = Path(os.environ.get("VIDEO_WORKBENCH_BGM_DIR") or data_home() / "bgm-library" / "incompetech")
man = sorted(json.loads((lib / "manifest.json").read_text(encoding="utf-8")), key=lambda m: -m.get("phone_db", -99))
my = out / "my-bgm"
my.mkdir(exist_ok=True)
melody, bassy = man[0], man[-1]
run(["ffmpeg", "-v", "error", "-y", "-i", str(lib / "tracks" / Path(melody["file"]).name), "-t", "15",
     "-c", "copy", str(my / "测试旋律.mp3")])
(my / "测试旋律.txt").write_text(melody["attribution"] + "\n", encoding="utf-8")
run(["ffmpeg", "-v", "error", "-y", "-i", str(lib / "tracks" / Path(bassy["file"]).name), "-t", "40", "-c", "copy",
     str(my / "测试低音.mp3")])

voice_args = []
if voice == "local":  # a preset in the voice library (CosyVoice's own sample, consent "demo": tests only)
    cv = Path(os.environ.get("COSYVOICE_HOME") or data_home() / "CosyVoice")
    r = subprocess.run([sys.executable, str(HERE / "voices.py"), "add", str(cv / "asset" / "zero_shot_prompt.wav"),
                        "--name", "验收示例", "--text", "希望你以后能够做的比我还好呦。", "--consent", "demo"], env=env)
    if r.returncode:
        raise SystemExit("voices.py add failed")
    voice_args = ["--voice-name", "验收示例"]

for script, args in (("make_spec.py", ["一茶茉莉白牡丹"]), ("copy_check.py", [])):
    r = subprocess.run([sys.executable, str(HERE / script), *args], env=env, cwd=work)
    if r.returncode:
        raise SystemExit(f"{script} failed")
r = subprocess.run([sys.executable, str(HERE / "produce.py"), "--voice", voice, *voice_args], env=env, cwd=work,
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
print(r.stdout[-6000:], r.stderr[-3000:], sep="\n")
print(f"produce.py exit {r.returncode}; delivery under {out / 'delivery'}")
if r.returncode:
    sys.exit(r.returncode)

summary = json.loads(r.stdout[r.stdout.rindex("\n{") + 1:r.stdout.rindex("}") + 1])
deliv = Path(summary["delivery"])
report = (deliv / "先看这里.md").read_text(encoding="utf-8")
problems = [msg for ok, msg in [
    (summary["bgm_source"] == "我的BGM", f"BGM should come from 我的BGM, got {summary['bgm_source']}"),
    (summary["bgm"] == ["测试旋律"], f"only the melody track should be used, got {summary['bgm']}"),
    ((deliv / "一茶茉莉白牡丹-无BGM版.mp4").is_file(), "无BGM版 missing"),
    ("测试低音" in report, "the skipped bass-only track is not explained in 先看这里.md"),
    (melody["attribution"] in (deliv / "发布文案.txt").read_text(encoding="utf-8"), "credit line missing in 发布文案.txt"),
    (voice != "local" or "验收示例" in summary["voice"], f"voice preset not used: {summary['voice']}"),
] if not ok]
if problems:
    raise SystemExit("acceptance checks failed:\n- " + "\n- ".join(problems))
print("acceptance checks passed (voice preset, 我的BGM, bass-only skip, looping short track, 无BGM版, credit)")
