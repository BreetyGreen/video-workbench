"""Turn a render into an editable Jianying (剪映) draft and register it as a NEW draft (never replaces anything).

usage (inside the project work dir):
  python make_draft.py <render_name> <draft_title> [--cover cover.jpg] [--bgm track.mp3] [--dry-run]

Tracks: graded base shots (+ native push-in keyframes), voice, action sound, subtitles in the render's caption style
(Jianying's bundled copy of the same open font, its own intro animation, highlighted words), optional licensed BGM
(pre-levelled ~19 dB under the voice; drag its volume in Jianying if needed). Close Jianying first.
Draft folder / index: auto-detected per OS, or set JIANYING_DRAFT_ROOT and JIANYING_DRAFT_INDEX.
--dry-run builds the media but writes nothing into Jianying.
"""
import argparse
import atexit
import copy
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import time
import uuid
from pathlib import Path

import pyJianYingDraft as d

import captions
from vw_common import IS_WIN, jianying_paths, jianying_running, run, work_dir

ap = argparse.ArgumentParser()
ap.add_argument("render")
ap.add_argument("title")
ap.add_argument("--cover")
ap.add_argument("--bgm")
ap.add_argument("--bgm-lufs", type=float, default=-35.0)
ap.add_argument("--dry-run", action="store_true")
a = ap.parse_args()

WORK = work_dir()
R = WORK / "renders" / a.render
SPEC = json.loads((WORK / "spec.json").read_text(encoding="utf-8"))
plan = json.loads((R / "edit-plan.json").read_text(encoding="utf-8"))
FPS = 30
us = lambda x: round(x * 1e6)

DRAFT_ROOT, INDEX = jianying_paths()
if not a.dry_run:
    if jianying_running():
        raise SystemExit("剪映正在运行：请先关闭剪映再生成草稿（避免同时写草稿索引）。")
    if not (DRAFT_ROOT.is_dir() and INDEX.is_file()):
        raise SystemExit(f"找不到剪映草稿目录或索引：{DRAFT_ROOT} / {INDEX}。先打开剪映建一个空草稿，"
                         "或设置 JIANYING_DRAFT_ROOT / JIANYING_DRAFT_INDEX。")
    assert not INDEX.is_symlink()
    if IS_WIN:
        assert not (INDEX.stat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)

ident = str(uuid.uuid4()).upper()
name = f"{a.title}-" + ident[:8]
draft_path = DRAFT_ROOT / name
assert not draft_path.exists()
stage = WORK / "draft-assets" / a.render
stage.mkdir(parents=True, exist_ok=True)

# ---- 1. base shots: graded, static framing at zoom0; the push-in becomes a native keyframe ----
grade = SPEC["color"]["ffmpeg_filter"]
shots = []
t_frames = 0
for n, p in enumerate(plan):
    src = p["take"]["file"]
    z = float(p["zoom0"])
    cx, cy = p["take"].get("subject_center") or [0.5, 0.5]
    cw, ch = 1080 / z, 1920 / z
    x = max(0, min(1080 - cw, cx * 1080 - cw / 2))
    y = max(0, min(1920 - ch, cy * 1920 - ch / 2))
    out = stage / f"shot-{n + 1:02d}.mp4"
    vf = (f"setpts=(PTS-STARTPTS)/{p['speed']},fps={FPS},crop={cw:.1f}:{ch:.1f}:{x:.1f}:{y:.1f},"
          f"scale=1080:1920:flags=lanczos,{grade},format=yuv420p")
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{p['src_in']:.3f}", "-t", f"{p['src_len'] + 0.2:.3f}", "-i", src,
         "-vf", vf, "-frames:v", str(p["frames"]), "-an", "-c:v", "libx264", "-crf", "15", "-preset", "medium", str(out)])
    shots.append({"file": out, "start_us": round(t_frames * 1e6 / FPS),
                  "dur_us": round((t_frames + p["frames"]) * 1e6 / FPS) - round(t_frames * 1e6 / FPS),
                  "end_scale": round((z + p["push"]) / z, 4), "folder": p["folder"]})
    t_frames += p["frames"]
total = t_frames / FPS

# ---- 2. audio: voice at -16 LUFS + levelled action sound, the same files as the preview mix ----
voice = stage / "配音.wav"
shutil.copy2(R / "voice_norm.wav", voice)
sfx = stage / "动作原声.wav"
shutil.copy2(R / "sfx.wav", sfx)
audio_tracks = [("配音（已剪气口）", voice, 1.0), ("动作原声", sfx, 1.0)]
bgm_credit = None
if a.bgm:
    bgm_src = Path(a.bgm).resolve()
    bgm = stage / "BGM.wav"
    run(["ffmpeg", "-v", "error", "-y", "-i", bgm_src, "-af",
         f"atrim=0:{total + 1:.3f},loudnorm=I={a.bgm_lufs}:TP=-6:LRA=7,afade=t=in:d=0.4,"
         f"afade=t=out:st={max(0, total - 1.2):.3f}:d=1.2", "-ar", "48000", "-ac", "2", "-t", f"{total:.3f}", bgm])
    audio_tracks.append(("BGM（CC BY，发布需署名）", bgm, 1.0))
    man = bgm_src.parent.parent / "manifest.json"
    if man.is_file():
        bgm_credit = next((r["attribution"] for r in json.loads(man.read_text(encoding="utf-8"))
                           if Path(r["file"]).name == bgm_src.name), None)

# ---- 3. subtitles: the render's cues, style and highlighted words (captions.json) ----
cap = json.loads((R / "captions.json").read_text(encoding="utf-8"))
STYLE = captions.STYLES[cap["style"]]
cues = [(c["start"], min(c["end"], total), c["text"], [tuple(x) for x in c.get("emph", [])]) for c in cap["cues"]]

if a.dry_run:
    print(json.dumps({"dry_run": True, "draft_root": str(DRAFT_ROOT), "index": str(INDEX), "shots": len(shots),
                      "subtitles": len(cues), "caption_style": cap["style"], "audio_tracks": [t[0] for t in audio_tracks],
                      "duration_s": round(total, 3)}, ensure_ascii=False, indent=1))
    sys.exit(0)

# ---- 4. write the draft ----
original_index = INDEX.read_bytes()
digest = hashlib.sha256(original_index).hexdigest()
index = json.loads(original_index)
assert isinstance(index.get("all_draft_store"), list)
_registered = {"ok": False}


def _cleanup():
    if not _registered["ok"] and draft_path.exists() and DRAFT_ROOT.resolve() in draft_path.resolve().parents:
        shutil.rmtree(draft_path, ignore_errors=True)
        print("已清理未注册的半成品草稿", draft_path, file=sys.stderr)


atexit.register(_cleanup)
script = d.DraftFolder(str(DRAFT_ROOT)).create_draft(name, 1080, 1920, fps=FPS, allow_replace=False)
assets = draft_path / "assets"
assets.mkdir()

vt = script.append_track(d.TrackSpec(d.TrackType.video, "镜头（已调色，推近为关键帧）"))
for s in shots:
    dst = assets / s["file"].name
    shutil.copy2(s["file"], dst)
    seg = d.VideoSegment(d.VideoMaterial(str(dst)), d.Timerange(s["start_us"], s["dur_us"]),
                         source_timerange=d.Timerange(0, s["dur_us"]), volume=0)
    if s["end_scale"] > 1.001:
        seg.add_keyframe(d.KeyframeProperty.uniform_scale, 0, 1.0)
        seg.add_keyframe(d.KeyframeProperty.uniform_scale, max(1, s["dur_us"] - 33333), s["end_scale"])
    script.add_segment(seg, vt)

for trackname, src, vol in audio_tracks:
    dst = assets / src.name
    shutil.copy2(src, dst)
    tr = script.append_track(d.TrackSpec(d.TrackType.audio, trackname))
    mat = d.AudioMaterial(str(dst))
    adur = min(us(total), int(mat.duration))
    script.add_segment(d.AudioSegment(mat, d.Timerange(0, adur), source_timerange=d.Timerange(0, adur), volume=vol), tr)

def rgb(hex_color: str):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


class RichText(d.TextSegment):
    """Jianying stores partial colouring as one style per character range; pyJianYingDraft writes one style."""

    def __init__(self, *args, ranges=(), accent=(1.0, 0.9, 0.0), **kw):
        super().__init__(*args, **kw)
        self._ranges, self._accent = [r for r in ranges if r[1] > r[0]], accent

    def export_material(self):
        mat = super().export_material()
        if not self._ranges:
            return mat
        content = json.loads(mat["content"])
        base = content["styles"][0]
        bounds = sorted({0, len(self.text), *(x for r in self._ranges for x in r)})
        styles = []
        for a0, b0 in zip(bounds, bounds[1:]):
            st_ = copy.deepcopy(base)
            st_["range"] = [a0, b0]
            if any(ra <= a0 and b0 <= rb for ra, rb in self._ranges):
                st_["fill"]["content"]["solid"]["color"] = list(self._accent)
            styles.append(st_)
        content["styles"] = styles
        mat["content"] = json.dumps(content, ensure_ascii=False)
        return mat


# same look as the mp4 using Jianying's bundled copies of the same open fonts and its own intro animations
jy_font = getattr(d.FontType, STYLE.get("jianying_font", ""), None)
jy_intro = getattr(d.TextIntro, STYLE.get("jianying_intro", ""), None)
stroke = STYLE.get("stroke", {})
shadow = STYLE.get("shadow")
bg = STYLE.get("jianying_background")
hl = STYLE.get("highlight", {})
tt = script.append_track(d.TrackSpec(d.TrackType.text, f"字幕（{cap['style']}）"))
for k, (s, e, text, emph) in enumerate(cues):
    s_us = us(s)
    e_us = min(us(e), us(cues[k + 1][0])) if k + 1 < len(cues) else min(us(e), us(total))
    seg = RichText(
        text, d.Timerange(s_us, e_us - s_us), font=jy_font,
        style=d.TextStyle(size=round(STYLE["size"] / 7.8, 1), bold=STYLE.get("weight", 700) >= 700 or not jy_font,
                          color=rgb(STYLE["fill"]), align=1, auto_wrapping=False),
        clip_settings=d.ClipSettings(transform_y=round(1 - 2 * (STYLE["y"] + 0.025), 3)),
        border=d.TextBorder(width=stroke.get("width", 0) * 8, color=rgb(stroke["color"])) if stroke else None,
        background=d.TextBackground(color=bg["color"], alpha=bg.get("alpha", 1.0),
                                    round_radius=bg.get("round_radius", 0.0)) if bg else None,
        shadow=d.TextShadow(alpha=shadow["alpha"], color=rgb(shadow["color"]), diffuse=shadow["blur"] * 2,
                            distance=max(1, abs(shadow["dy"]))) if shadow else None,
        ranges=emph if hl.get("fill") and not hl.get("box") else (), accent=rgb(hl.get("fill", "#FFE500")))
    if jy_intro is not None:
        seg.add_animation(jy_intro, max(1, min(round(STYLE.get("anim_s", 0.14) * 2e6), e_us - s_us)))
    script.add_segment(seg, tt)
script.save()

content = json.loads((draft_path / "draft_content.json").read_text(encoding="utf-8"))
content["id"] = ident
content["name"] = name
(draft_path / "draft_content.json").write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
(draft_path / "draft_info.json").write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
cover = Path(a.cover) if a.cover else None
if cover and cover.is_file():
    shutil.copy2(cover, draft_path / "draft_cover.jpg")
meta = json.loads((draft_path / "draft_meta_info.json").read_text(encoding="utf-8"))
now = int(time.time() * 1e6)
meta.update(draft_id=ident, draft_name=name, draft_fold_path=str(draft_path), draft_root_path=str(DRAFT_ROOT),
            draft_cover=str(draft_path / "draft_cover.jpg"), tm_draft_create=now, tm_draft_modified=now,
            tm_duration=us(total))
(draft_path / "draft_meta_info.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
for kind in ("videos", "audios"):
    for mat in content["materials"].get(kind, []):
        p = Path(mat["path"])
        assert p.is_file() and assets.resolve() in p.resolve().parents, p

# ---- 5. register as a new entry (index backed up, atomic replace, concurrent-change check) ----
before = len(index["all_draft_store"])
entry = {**meta, "draft_json_file": str(draft_path / "draft_content.json"), "draft_is_cloud_temp_draft": False,
         "draft_timeline_materials_size": sum(p.stat().st_size for p in assets.iterdir()),
         "streaming_edit_draft_ready": True}
index["all_draft_store"].insert(0, entry)
if isinstance(index.get("draft_ids"), list):
    index["draft_ids"].append(ident)
assert hashlib.sha256(INDEX.read_bytes()).hexdigest() == digest, "草稿索引被同时修改，已停止"
backup = WORK / f"jianying-root-index-before-{ident[:8]}.json"
backup.write_bytes(original_index)
tmp = INDEX.with_name(f"root_meta_info.{ident}.tmp")
tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
os.replace(tmp, INDEX)
_registered["ok"] = True
receipt = {"draft_name": name, "draft_path": str(draft_path), "draft_id": ident, "duration_s": round(total, 3),
           "tracks": {"video": len(shots), "audio": len(audio_tracks), "subtitles": len(cues)},
           "bgm_credit": bgm_credit, "keyframed_shots": sum(1 for s in shots if s["end_scale"] > 1.001),
           "existing_drafts_preserved": before, "index_backup": str(backup), "native_playback_verified": False}
(draft_path / "workbench-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
(WORK / f"剪映草稿-{a.render}.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(receipt, ensure_ascii=False, indent=1))
