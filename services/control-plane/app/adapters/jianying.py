from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pyJianYingDraft as draft

from app.schemas.editing import EditingTimeline


SUPPORTED_TARGETS = {"5.x", "6+"}


@dataclass(frozen=True)
class MediaSegment:
    source: Path
    start_us: int
    duration_us: int
    source_start_us: int = 0
    volume: float = 1.0


@dataclass(frozen=True)
class TextSegment:
    text: str
    start_us: int
    duration_us: int
    size: float = 8.0
    bold: bool = True


@dataclass
class EditPlan:
    task_root: Path
    title: str
    duration_us: int
    videos: list[MediaSegment] = field(default_factory=list)
    audios: list[MediaSegment] = field(default_factory=list)
    texts: list[TextSegment] = field(default_factory=list)


@dataclass(frozen=True)
class DraftPackage:
    draft_dir: Path
    zip_path: Path
    track_counts: dict[str, int]
    compatibility: dict[str, object]


def _ensure_inside_task_root(path: Path, task_root: Path) -> Path:
    resolved_root = task_root.resolve()
    resolved_path = path.resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ValueError(f"Media path is outside the task root: {resolved_path}")
    if not resolved_path.is_file():
        raise FileNotFoundError(f"Media path does not exist: {resolved_path}")
    return resolved_path


def _copy_asset(source: Path, assets_dir: Path, used_names: set[str]) -> Path:
    name = source.name
    if name in used_names:
        name = f"{source.stem}-{uuid4().hex[:8]}{source.suffix.lower()}"
    used_names.add(name)
    destination = assets_dir / name
    shutil.copy2(source, destination)
    return destination


def _add_tracks(script: draft.ScriptFile, plan: EditPlan, assets_dir: Path) -> dict[str, int]:
    used_names: set[str] = set()
    counts = {"video": len(plan.videos), "audio": len(plan.audios), "text": len(plan.texts)}

    if plan.videos:
        video_track = script.append_track(draft.TrackSpec(draft.TrackType.video, "video"))
        for item in plan.videos:
            source = _ensure_inside_task_root(item.source, plan.task_root)
            copied = _copy_asset(source, assets_dir, used_names)
            material = draft.VideoMaterial(str(copied), copied.name)
            script.add_segment(
                draft.VideoSegment(
                    material,
                    draft.Timerange(item.start_us, item.duration_us),
                    source_timerange=draft.Timerange(item.source_start_us, item.duration_us),
                    volume=item.volume,
                ),
                video_track,
            )

    if plan.audios:
        audio_track = script.append_track(draft.TrackSpec(draft.TrackType.audio, "audio"))
        for item in plan.audios:
            source = _ensure_inside_task_root(item.source, plan.task_root)
            copied = _copy_asset(source, assets_dir, used_names)
            material = draft.AudioMaterial(str(copied), copied.name)
            script.add_segment(
                draft.AudioSegment(
                    material,
                    draft.Timerange(item.start_us, item.duration_us),
                    source_timerange=draft.Timerange(item.source_start_us, item.duration_us),
                    volume=item.volume,
                ),
                audio_track,
            )

    if plan.texts:
        text_track = script.append_track(draft.TrackSpec(draft.TrackType.text, "text"))
        for item in plan.texts:
            script.add_segment(
                draft.TextSegment(
                    item.text,
                    draft.Timerange(item.start_us, item.duration_us),
                    style=draft.TextStyle(
                        size=item.size,
                        bold=item.bold,
                        color=(1.0, 1.0, 1.0),
                        align=1,
                        auto_wrapping=True,
                        max_line_width=0.78,
                    ),
                    border=draft.TextBorder(alpha=1.0, color=(0.03, 0.03, 0.03), width=38),
                    shadow=draft.TextShadow(alpha=0.7, diffuse=12, distance=4),
                ),
                text_track,
            )

    return counts


def edit_plan_from_timeline(timeline: EditingTimeline, task_root: Path) -> EditPlan:
    """Serialize the same timeline used by the renderer into editable Jianying tracks."""

    def timerange_us(start_seconds: float, end_seconds: float) -> tuple[int, int]:
        start_us = round(start_seconds * 1_000_000)
        end_us = round(end_seconds * 1_000_000)
        return start_us, max(1, end_us - start_us)

    videos = [
        MediaSegment(
            source=Path(clip.source_path),
            start_us=timerange_us(clip.timeline_start_seconds, clip.timeline_end_seconds)[0],
            duration_us=timerange_us(clip.timeline_start_seconds, clip.timeline_end_seconds)[1],
            source_start_us=round(clip.source_start_seconds * 1_000_000),
        )
        for clip in timeline.clips
    ]
    texts = [
        TextSegment(
            text=cue.text,
            start_us=timerange_us(cue.start_seconds, cue.end_seconds)[0],
            duration_us=timerange_us(cue.start_seconds, cue.end_seconds)[1],
            size=8.0,
            bold=True,
        )
        for cue in timeline.captions
    ]
    audios = []
    if timeline.audio.bgm_path:
        audios.append(
            MediaSegment(
                source=Path(timeline.audio.bgm_path),
                start_us=0,
                duration_us=round(timeline.actual_duration_seconds * 1_000_000),
                source_start_us=0,
                volume=10 ** (timeline.audio.bgm_gain_db / 20),
            )
        )
    return EditPlan(
        task_root=task_root,
        title=timeline.title,
        duration_us=round(timeline.actual_duration_seconds * 1_000_000),
        videos=videos,
        audios=audios,
        texts=texts,
    )


def build_draft(plan: EditPlan, output_root: Path, *, target: str = "6+") -> DraftPackage:
    if target not in SUPPORTED_TARGETS:
        raise ValueError(f"Unsupported Jianying target: {target}")
    if plan.duration_us <= 0:
        raise ValueError("Edit plan duration must be positive")

    resolved_output = output_root.resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    draft_name = f"{plan.title.strip() or 'video'}-{uuid4().hex[:8]}"
    folder = draft.DraftFolder(str(resolved_output))
    script = folder.create_draft(draft_name, 1080, 1920, fps=30)
    draft_dir = resolved_output / draft_name
    assets_dir = draft_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    track_counts = _add_tracks(script, plan, assets_dir)
    script.save()

    content_path = draft_dir / "draft_content.json"
    if target == "6+":
        info_path = draft_dir / "draft_info.json"
        shutil.copy2(content_path, info_path)

    compatibility: dict[str, object] = {
        "target": target,
        "generator": "pyJianYingDraft",
        "generator_version": "0.3.0",
        "canvas": {"width": 1080, "height": 1920, "fps": 30},
        "opened_in_local_jianying": False,
        "requires_local_validation": True,
        "notes": "Newer Jianying versions may migrate draft fields when first opened.",
    }
    (draft_dir / "compatibility.json").write_text(
        json.dumps(compatibility, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    zip_path = resolved_output / f"{draft_name}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(draft_dir.rglob("*")):
            if item.is_file():
                archive.write(item, Path(draft_name) / item.relative_to(draft_dir))

    return DraftPackage(
        draft_dir=draft_dir,
        zip_path=zip_path,
        track_counts=track_counts,
        compatibility=compatibility,
    )
