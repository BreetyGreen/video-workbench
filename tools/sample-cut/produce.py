"""Autopilot final stage: everything after the judgement calls, in one command, no questions.

usage (inside the project work dir, after takes/selected-takes.json, copy.json and spec.json exist):
  python produce.py [--voice auto|cloud|local] [--cloud-voice longxiaochun_v2] [--bgm-versions 3] [--bgm-lufs -20] [--draft]
                   [--narration voice/x/narration]   (reuse an approved voice instead of synthesizing)
steps: copy_check -> voice (whole script) -> narration timing -> render -> BGM versions -> QA -> cover ->
       phone previews -> delivery folder with 先看这里.md, 发布文案.txt, BGM credits
settings: <data_home>/sample-cut.json (voice engine, cloud voice, own-voice prompt, delivery dir) - see AUTOPILOT.md
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from vw_common import IS_MAC, IS_WIN, REPO, data_home, dashscope_key, encode_checked, run, work_dir

HERE = Path(__file__).resolve().parent
WORK = work_dir()
CFG_PATH = data_home() / "sample-cut.json"
CFG = json.loads(CFG_PATH.read_text(encoding="utf-8")) if CFG_PATH.is_file() else {}
ap = argparse.ArgumentParser()
ap.add_argument("--voice", default=CFG.get("voice_engine", "auto"), choices=["auto", "cloud", "local"])
ap.add_argument("--cloud-voice", default=CFG.get("cloud_voice", "longxiaochun_v2"))
ap.add_argument("--bgm-versions", type=int, default=CFG.get("bgm_versions", 3))
ap.add_argument("--bgm-lufs", type=float, default=CFG.get("bgm_lufs", -20.0),
                help="BGM loudness before ducking; -20 = ~8-10 dB under the voice on a phone. Higher = louder music")
ap.add_argument("--draft", action="store_true", default=CFG.get("jianying_draft", False))
ap.add_argument("--name", default="final")
ap.add_argument("--narration", help="reuse an existing narration dir (narration.json + narration.wav)")
a = ap.parse_args()
env = {**os.environ, "SAMPLE_CUT_WORK": str(WORK), "PYTHONIOENCODING": "utf-8"}
log = []


def step(script, *args, ok_codes=(0,)):
    r = subprocess.run([sys.executable, str(HERE / script), *map(str, args)], env=env, cwd=WORK, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    print(f"--- {script} {' '.join(map(str, args))[:80]} -> {r.returncode}", flush=True)
    if r.returncode not in ok_codes:
        print(r.stdout[-1500:], r.stderr[-2500:], sep="\n")
        raise SystemExit(f"{script} failed")
    log.append(script)
    return r.stdout


copy = json.loads((WORK / "copy.json").read_text(encoding="utf-8"))
spec = json.loads((WORK / "spec.json").read_text(encoding="utf-8"))
title = spec.get("cover", {}).get("title") or copy.get("product", "成片")
step("copy_check.py")

# ---------- voice ----------
try:
    have_key = bool(dashscope_key())
except SystemExit:
    have_key = False
cv_home = Path(os.environ.get("COSYVOICE_HOME") or CFG.get("cosyvoice_home") or data_home() / "CosyVoice").expanduser()
cv_py = cv_home / (".venv/Scripts/python.exe" if IS_WIN else ".venv/bin/python")
text = "".join(s["text"] for s in copy["sentences"])
if a.narration:  # reuse an approved voice: skip synthesis and timing
    narr_dir = Path(a.narration).resolve()
    if not (narr_dir / "narration.json").is_file():
        raise SystemExit(f"--narration 目录里没有 narration.json：{narr_dir}")
    _n = json.loads((narr_dir / "narration.json").read_text(encoding="utf-8"))
    voice_label = f"沿用已有配音（{_n.get('engine', '?')} / {_n.get('voice', '?')}）"
else:
    engine = a.voice
    if engine == "auto":
        engine = "local" if CFG.get("own_voice_prompt") and cv_py.exists() else ("cloud" if have_key else "local")
    if engine == "cloud":
        if not have_key:
            raise SystemExit("云端配音需要 VIDEO_WORKBENCH_DASHSCOPE_API_KEY；或装 CosyVoice 走本机配音")
        vdir = WORK / "voice" / a.cloud_voice
        vdir.mkdir(parents=True, exist_ok=True)
        whole = vdir / "whole.mp3"
        if not whole.exists():
            import dashscope
            from dashscope.audio.tts_v2 import SpeechSynthesizer
            dashscope.api_key = dashscope_key()
            audio = SpeechSynthesizer(model="cosyvoice-v2", voice=a.cloud_voice).call(text)  # whole script: natural prosody
            if not audio:
                raise SystemExit("云端配音没有返回音频")
            whole.write_bytes(audio)
        voice_label = f"云端 CosyVoice（{a.cloud_voice}）"
    else:
        if not cv_py.exists():
            raise SystemExit(f"本机配音没有安装（{cv_home}）。先运行 tools/cosyvoice/install.sh，或设置百炼 Key 走云端配音")
        prompt = CFG.get("own_voice_prompt") or str(cv_home / "asset" / "zero_shot_prompt.wav")
        prompt_text = CFG.get("own_voice_text") or "希望你以后能够做的比我还好呦。"
        vdir = WORK / "voice" / ("own" if CFG.get("own_voice_prompt") else "cosyvoice-demo")
        whole = vdir / "whole.wav"
        if not whole.exists():
            r = subprocess.run([str(cv_py), str(REPO / "tools" / "cosyvoice" / "clone_tts.py"), "--prompt", prompt,
                                "--prompt-text", prompt_text, "--text-file", str(WORK / "copy.json"), "--out", str(whole)],
                               env={**env, "COSYVOICE_HOME": str(cv_home)}, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode:
                print(r.stderr[-2000:])
                raise SystemExit("本机配音失败")
        voice_label = "本机 CosyVoice（" + ("自己的声音" if CFG.get("own_voice_prompt") else "官方示例音色，仅演示") + "）"
    narr_dir = vdir / "narration"
    env["VOICE_ENGINE"] = engine
    step("narration_from_whole.py", whole, narr_dir)
narr = json.loads((narr_dir / "narration.json").read_text(encoding="utf-8"))

# ---------- render ----------
render_out = json.loads(step("render.py", narr_dir, a.name).strip().splitlines()[-1])
R = WORK / "renders" / a.name
final = R / f"{a.name}.mp4"

# ---------- BGM: pick tracks by the product's mood, mix N versions ----------
lib = Path(os.environ.get("VIDEO_WORKBENCH_BGM_DIR") or data_home() / "bgm-library" / "incompetech")
manifest = json.loads((lib / "manifest.json").read_text(encoding="utf-8")) if (lib / "manifest.json").is_file() else []
if manifest:  # score tracks by phone-audible share once; skip bass-only grooves that vanish on phone speakers
    import bgm_analyze
    manifest = bgm_analyze.analyze()
tracks = [m for m in manifest if (lib / "tracks" / Path(m["file"]).name).is_file()]
audible = [m for m in tracks if m.get("phone_db", 0) >= -6.0]
tracks = audible if len(audible) >= 3 else tracks
versions = []
if tracks and a.bgm_versions > 0:
    sys.path.insert(0, str(HERE))
    import captions
    blob = copy.get("product", "") + text
    moods = {m for m, kws in captions.LIB["mood_keywords"].items() if any(k in blob for k in kws)}
    want = {"茶": ["Relaxed", "Calming", "Light", "Bright"], "健康": ["Bright", "Light", "Uplifting"],
            "饮品": ["Bright", "Uplifting", "Carefree", "Happy"], "甜品": ["Playful", "Happy", "Quirky", "Bouncy"],
            "零食": ["Happy", "Bouncy", "Funky", "Playful"], "辣味": ["Funky", "Groovy", "Bouncy"],
            "母婴": ["Playful", "Light", "Happy"], "日用": ["Bright", "Uplifting", "Light"]}
    words = [w for m in moods for w in want.get(m, [])] or ["Bright", "Happy", "Uplifting"]
    score = lambda m: (sum(w.lower() in (m.get("feel") or "").lower() for w in words) * 10 + m.get("score", 0)
                       + 2 * m.get("phone_db", -6))  # prefer melody that a phone speaker can play
    ranked = sorted(tracks, key=lambda m: (-score(m), m["title"]))
    seed = sum(map(ord, copy.get("product", ""))) % max(1, min(6, len(ranked)))
    chosen = (ranked[seed:] + ranked[:seed])[:a.bgm_versions]  # different products get different tracks
    for m in chosen:
        t = Path(m["file"]).name
        out = R / f"{a.name}-BGM-{Path(t).stem}.mp4"
        res = json.loads(step("add_bgm.py", final, lib / "tracks" / t, out, a.bgm_lufs).strip().splitlines()[-1])
        versions.append({"title": m["title"], "file": out, "credit": m["attribution"], **res})
else:
    print("! BGM library missing: run bgm_pick.py + bgm_download.py once; delivering without BGM")

# ---------- QA ----------
qa_rc = subprocess.run([sys.executable, str(HERE / "qa.py"), a.name, *[str(v["file"]) for v in versions]], env=env,
                       cwd=WORK, capture_output=True, text=True, encoding="utf-8", errors="replace")
print(qa_rc.stdout)
qa = json.loads((R / "qa.json").read_text(encoding="utf-8"))

# ---------- cover: graded opening frame + product title in the caption style ----------
cover = R / "封面.jpg"
frame = R / "cover-frame.png"
run(["ffmpeg", "-v", "error", "-y", "-ss", "0.7", "-i", R / "picture.mp4", "-frames:v", "1", "-update", "1", frame])
from PIL import Image  # noqa: E402

sys.path.insert(0, str(HERE))
import captions  # noqa: E402

style = dict(captions.STYLES[render_out.get("caption_style", "经典带货")])
style["size"] = min(150, int(980 / max(2, len(title)) * 0.95))
img = Image.open(frame).convert("RGBA")
line, pad = captions.draw_line(title, [], style)
img.alpha_composite(line, (0, int(img.height * 0.42) - line.height // 2))
img.convert("RGB").save(cover, quality=92)

# ---------- delivery folder ----------
root = Path(os.environ.get("VIDEO_WORKBENCH_DELIVERIES_DIR") or CFG.get("deliveries_dir")
            or (Path.home() / "Movies" / "VideoWorkbench 成片" if IS_MAC else REPO / "data" / "deliveries"))
deliv = root / dt.date.today().isoformat() / re.sub(r'[\\/:*?"<>|]', "_", title)
(deliv / "手机预览").mkdir(parents=True, exist_ok=True)
main = versions[0]["file"] if versions else final
shutil.copy2(main, deliv / f"{title}-成片.mp4")
if len(versions) > 1:
    (deliv / "BGM备选").mkdir(exist_ok=True)
    for v in versions[1:]:
        shutil.copy2(v["file"], deliv / "BGM备选" / f"{title}-BGM-{v['title']}.mp4")
for src, name in [(main, f"{title}-成片"), *[(v["file"], f"{title}-BGM-{v['title']}") for v in versions[1:]]]:
    pv = deliv / "手机预览" / f"{name}-720p.mp4"
    encode_checked(lambda c, src=src, pv=pv: ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", "scale=720:-2",
                                              "-c:v", "libx264", "-crf", "24", "-preset", "medium", "-pix_fmt", "yuv420p",
                                              *c, "-movflags", "+faststart", str(pv)], pv, bitrate="160k")
shutil.copy2(cover, deliv / "封面.jpg")
shutil.copy2(R / "captions.srt", deliv / "字幕.srt")
shutil.copy2(R / "qa.json", deliv / "质检.json")
credit = versions[0]["credit"] if versions else ""
facts = copy.get("facts_from_package", [])
post = copy.get("post_caption") or f"{title}｜{copy['sentences'][1]['text'].rstrip('，。！')}"
(deliv / "发布文案.txt").write_text(post + "\n\n" + (f"BGM：{credit}\n" if credit else ""), encoding="utf-8")
if a.draft:
    step("make_draft.py", a.name, title, "--cover", cover,
         *(["--bgm", str(lib / "tracks" / versions[0]["bgm"])] if versions else []))
notes = (WORK / "notes.md").read_text(encoding="utf-8") if (WORK / "notes.md").is_file() else ""
qa_rows = "\n".join(f"| {'✓' if c['ok'] else ('✗' if c['level'] == 'fail' else '!')} | {c['item']} | {c['detail']} |"
                    for c in qa["checks"])
report = f"""# {title}（全自动生成，{dt.date.today().isoformat()}）

| 文件 | 说明 |
|---|---|
| `{title}-成片.mp4` | 1080p 成片{('，BGM：' + versions[0]['title']) if versions else '（没有 BGM）'} |
| `BGM备选/` | 换了 BGM 的同一条片子{'' if len(versions) > 1 else '（本次没有）'} |
| `手机预览/` | 720p 压缩版，方便手机上看 |
| `封面.jpg` | 第一个镜头 + 商品名 |
| `发布文案.txt` | 发布时贴进抖音简介，**含 BGM 署名，必须保留** |
| `字幕.srt`、`质检.json` | 字幕文件、自动质检结果 |

- 时长 {render_out['duration']} 秒，{render_out['shots']} 个镜头（平均 {render_out['avg_shot_s']} 秒），字幕样式「{render_out.get('caption_style')}」
- 配音：{voice_label}，{narr.get('cps')} 字/秒，对齐方式：{'语音识别逐字对齐' if narr.get('timing', 'asr') == 'asr' else '按字数估算（没有百炼 Key）'}
- BGM：{'；'.join(v['title'] for v in versions) or '无'}（Kevin MacLeod，CC BY 4.0，需署名）

## 自动质检：{'通过' if qa['passed'] else '有不合格项，见下表'}

| | 项目 | 结果 |
|---|---|---|
{qa_rows}

## 文案只用了包装上印的信息

{chr(10).join('- ' + f for f in facts)}

没写：{'、'.join(copy.get('not_claimed', [])) or '价格、库存、功效、和其他品牌比较'}

## 素材与选择说明

{notes or '（无）'}

## 发布

在抖音 App 或 creator.douyin.com 上传 `{title}-成片.mp4`，封面用 `封面.jpg`，简介贴 `发布文案.txt` 的内容，最后由本人点发布。
"""
(deliv / "先看这里.md").write_text(report, encoding="utf-8")
summary = {"delivery": str(deliv), "main": str(deliv / f"{title}-成片.mp4"), "voice": voice_label,
           "caption_style": render_out.get("caption_style"), "bgm": [v["title"] for v in versions],
           "qa_passed": qa["passed"], "hard_fails": qa["hard_fails"], "warnings": qa["warnings"]}
print(json.dumps(summary, ensure_ascii=False, indent=1))
sys.exit(0 if qa["passed"] else 2)
