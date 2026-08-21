from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from app.adapters.jianying import (
    EditPlan,
    MediaSegment,
    TextSegment,
    build_draft,
    edit_plan_from_timeline,
)
from app.schemas.editing import CaptionCue, EditingTimeline, TimelineClip


@pytest.fixture
def sample_plan(tmp_path: Path, ffmpeg_bin: str) -> EditPlan:
    task_root = tmp_path / "task"
    task_root.mkdir()
    video = task_root / "video.mp4"
    audio = task_root / "audio.wav"
    subprocess.run(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:d=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=600:sample_rate=48000",
            "-t",
            "2",
            "-c:a",
            "pcm_s16le",
            str(audio),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return EditPlan(
        task_root=task_root,
        title="宠物日常",
        duration_us=2_000_000,
        videos=[MediaSegment(source=video, start_us=0, duration_us=2_000_000)],
        audios=[MediaSegment(source=audio, start_us=0, duration_us=2_000_000)],
        texts=[
            TextSegment(
                text="今天也要开心呀",
                start_us=0,
                duration_us=2_000_000,
            )
        ],
    )


def test_build_draft_zip_contains_editable_tracks(tmp_path: Path, sample_plan: EditPlan):
    package = build_draft(sample_plan, tmp_path / "drafts", target="6+")

    assert package.zip_path.exists()
    assert package.track_counts == {"video": 1, "audio": 1, "text": 1}
    assert package.compatibility["target"] == "6+"
    assert package.compatibility["opened_in_local_jianying"] is False

    with zipfile.ZipFile(package.zip_path) as archive:
        names = archive.namelist()
        assert any(name.endswith("draft_info.json") for name in names)
        assert any(name.endswith("assets/video.mp4") for name in names)
        draft_name = next(name for name in names if name.endswith("draft_info.json"))
        draft = json.loads(archive.read(draft_name))
        assert len(draft["tracks"]) == 3


def test_build_draft_rejects_media_outside_task_root(tmp_path: Path, sample_plan: EditPlan):
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    sample_plan.videos[0] = MediaSegment(
        source=outside,
        start_us=0,
        duration_us=2_000_000,
    )

    with pytest.raises(ValueError, match="outside the task root"):
        build_draft(sample_plan, tmp_path / "drafts", target="6+")


def test_unknown_target_is_rejected(tmp_path: Path, sample_plan: EditPlan):
    with pytest.raises(ValueError, match="Unsupported Jianying target"):
        build_draft(sample_plan, tmp_path / "drafts", target="unknown")


def test_timeline_is_converted_to_editable_jianying_segments(sample_plan: EditPlan):
    video = sample_plan.videos[0].source
    audio = sample_plan.audios[0].source
    timeline = EditingTimeline(
        title="统一时间线",
        target_duration_seconds=1.5,
        actual_duration_seconds=1.5,
        clips=[
            TimelineClip(
                material_id="one",
                source_path=str(video),
                source_start_seconds=0.25,
                source_end_seconds=1.75,
                timeline_start_seconds=0,
                timeline_end_seconds=1.5,
                score=9,
                reason="hook:speech",
                has_audio=True,
            )
        ],
        captions=[
            CaptionCue(
                material_id="one",
                text="这是可编辑字幕",
                start_seconds=0.1,
                end_seconds=1.2,
                source_start_seconds=0.35,
                source_end_seconds=1.45,
            )
        ],
        audio={"bgm_path": str(audio), "bgm_gain_db": -18},
    )

    plan = edit_plan_from_timeline(timeline, sample_plan.task_root)

    assert plan.duration_us == 1_500_000
    assert plan.videos[0].source_start_us == 250_000
    assert plan.videos[0].duration_us == 1_500_000
    assert plan.texts[0].text == "这是可编辑字幕"
    assert plan.texts[0].bold is True
    assert plan.audios[0].volume == pytest.approx(10 ** (-18 / 20))


def test_fractional_contiguous_captions_remain_non_overlapping_after_microsecond_conversion(
    sample_plan: EditPlan,
):
    video = sample_plan.videos[0].source
    boundary = 11.70995744680851
    timeline = EditingTimeline(
        title="连续字幕",
        target_duration_seconds=14.21923404255319,
        actual_duration_seconds=14.21923404255319,
        clips=[
            TimelineClip(
                material_id="one",
                source_path=str(video),
                source_start_seconds=0,
                source_end_seconds=14.21923404255319,
                timeline_start_seconds=0,
                timeline_end_seconds=14.21923404255319,
                score=9,
                reason="hook:visual",
                has_audio=True,
            )
        ],
        captions=[
            CaptionCue(
                material_id="voiceover",
                text="上一句",
                start_seconds=4.809446808510638,
                end_seconds=boundary,
                source_start_seconds=4.809446808510638,
                source_end_seconds=boundary,
            ),
            CaptionCue(
                material_id="voiceover",
                text="下一句",
                start_seconds=boundary,
                end_seconds=14.21923404255319,
                source_start_seconds=boundary,
                source_end_seconds=14.21923404255319,
            ),
        ],
    )

    plan = edit_plan_from_timeline(timeline, sample_plan.task_root)

    assert plan.texts[0].start_us + plan.texts[0].duration_us <= plan.texts[1].start_us
