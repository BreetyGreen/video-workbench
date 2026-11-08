"""Automatic QA of a render against the sample standard (spec.json targets).

usage (inside the project work dir): python qa.py <render_name> [<extra.mp4> ...]
checks the render's own mp4 plus any extra versions (BGM mixes): duration, shots, average shot length, speaking rate,
voice ASR match, loudness, true peak, black frames, captions. Writes renders/<name>/qa.json; exit 1 on a hard fail.
"""
import json
import re
import sys
from pathlib import Path

from vw_common import integrated_lufs, run, true_peak, work_dir

WORK = work_dir()
name = sys.argv[1]
R = WORK / "renders" / name
spec = json.loads((WORK / "spec.json").read_text(encoding="utf-8"))
tg = spec["targets"]
plan = json.loads((R / "edit-plan.json").read_text(encoding="utf-8"))
cap = json.loads((R / "captions.json").read_text(encoding="utf-8")) if (R / "captions.json").exists() else {"cues": []}
info = json.loads((R / "render-info.json").read_text(encoding="utf-8")) if (R / "render-info.json").exists() else {}
videos = [R / f"{name}.mp4", *map(Path, sys.argv[2:])]
checks = []  # (level, item, ok, detail)


def check(level, item, ok, detail):
    checks.append({"level": level, "item": item, "ok": bool(ok), "detail": detail})


dur = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", videos[0]]).stdout)
lo, hi = tg["duration_s"]
check("warn", "时长", lo <= dur <= hi + 0.5, f"{dur:.1f} 秒（标准 {lo}-{hi}）")
n = len(plan)
check("warn", "镜头数", tg["shots"][0] <= n <= tg["shots"][1], f"{n} 个（标准 {tg['shots'][0]}-{tg['shots'][1]}）")
avg = dur / max(1, n)
check("warn", "平均镜头", tg["avg_shot_s"][0] <= avg <= tg["avg_shot_s"][1] + 0.1,
      f"{avg:.2f} 秒（标准 {tg['avg_shot_s'][0]}-{tg['avg_shot_s'][1]}）")
longest = max(p["frames"] for p in plan) / 30
check("warn", "最长镜头", longest <= tg["shot_s_range"][1] + 0.6, f"{longest:.2f} 秒")
nj = Path(info.get("narration_dir", "-")) / "narration.json"
narr = json.loads(nj.read_text(encoding="utf-8")) if nj.is_file() else None
if narr:
    cps = narr.get("cps", 0)
    check("warn", "语速", tg["voice_chars_per_s"][0] - 0.3 <= cps <= tg["voice_chars_per_s"][1] + 0.3,
          f"{cps} 字/秒（标准 {tg['voice_chars_per_s'][0]}-{tg['voice_chars_per_s'][1]}）")
    if narr.get("asr_char_match") is not None:
        check("fail", "配音读字准确", narr["asr_char_match"] >= 0.9, f"语音识别比对 {narr['asr_char_match']:.0%}")
check("fail", "字幕", len(cap["cues"]) > 0, f"{len(cap['cues'])} 条，样式「{cap.get('style', '?')}」")
for v in videos:
    lufs, tp = integrated_lufs(v), true_peak(v)
    check("fail", f"响度 {v.name}", abs(lufs + 14) <= 1.0, f"{lufs:.1f} LUFS（标准 -14±1）")
    check("fail", f"真峰值 {v.name}", tp <= -1.0, f"{tp:.1f} dBTP（标准 ≤ -1.5，> -1 不能交付）")
bd = run(["ffmpeg", "-hide_banner", "-i", videos[0], "-vf", "blackdetect=d=0.2:pix_th=0.08", "-an", "-f", "null", "-"]).stderr
blacks = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", bd)
check("fail", "黑场", not blacks, "无" if not blacks else "；".join(f"{a}-{b}s" for a, b in blacks))
hard = [c for c in checks if c["level"] == "fail" and not c["ok"]]
soft = [c for c in checks if c["level"] == "warn" and not c["ok"]]
out = {"render": name, "passed": not hard, "hard_fails": len(hard), "warnings": len(soft), "checks": checks}
(R / "qa.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
for c in checks:
    print(("✓" if c["ok"] else ("✗" if c["level"] == "fail" else "!")), c["item"], c["detail"])
sys.exit(1 if hard else 0)
