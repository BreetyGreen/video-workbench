from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.editing import (
    EditingTimeline,
    FrameEvidence,
    MediaAnalysis,
    ReferencePacingProfile,
    ReferenceVideoBrief,
    SceneInterval,
    SilenceInterval,
    TimelineClip,
    TranscriptResult,
    TranscriptSegment,
    TranscriptWord,
)
from app.services.timeline_service import TimelinePlanner, invert_intervals, validate_timeline
from app.services.audio_routing_service import AudioRoutingDecision


def analysis(
    tmp_path: Path,
    material_id: str,
    *,
    duration: float = 8,
    transcript_segments: list[TranscriptSegment] | None = None,
    scene_score: float = 0.4,
) -> MediaAnalysis:
    source = tmp_path / f"{material_id}.mp4"
    source.write_bytes(b"video")
    return MediaAnalysis(
        material_id=material_id,
        source_path=str(source),
        duration_seconds=duration,
        width=1920,
        height=1080,
        has_audio=True,
        transcript=TranscriptResult(
            language="zh",
            language_probability=0.97,
            duration_seconds=duration,
            segments=transcript_segments or [],
        ),
        scenes=[
            SceneInterval(start_seconds=0, end_seconds=4, score=scene_score),
            SceneInterval(start_seconds=4, end_seconds=duration, score=scene_score + 0.1),
        ],
        frames=[
            FrameEvidence(
                timestamp_seconds=0.1,
                image_path=str(tmp_path / f"{material_id}.jpg"),
                width=1920,
                height=1080,
                brightness=120,
                contrast=45,
                sharpness=350,
            )
        ],
    )


def speech(text: str, start: float, end: float, confidence: float = 0.9) -> TranscriptSegment:
    return TranscriptSegment(
        text=text,
        start_seconds=start,
        end_seconds=end,
        confidence=confidence,
        words=[
            TranscriptWord(
                text=text,
                start_seconds=start,
                end_seconds=end,
                probability=confidence,
            )
        ],
    )


def test_invert_intervals_removes_long_silence_and_keeps_edges():
    kept = invert_intervals(
        4.0,
        [
            SilenceInterval(start_seconds=0.6, end_seconds=1.8),
            SilenceInterval(start_seconds=3.0, end_seconds=3.9),
        ],
        minimum_keep_seconds=0.3,
    )

    assert kept == [(0.0, 0.6), (1.8, 3.0)]


def test_planner_uses_multiple_sources_drops_fillers_and_remaps_captions(tmp_path: Path):
    first = analysis(
        tmp_path,
        "a",
        transcript_segments=[speech("嗯", 0.0, 0.8, 0.4), speech("先看最后的效果", 1.0, 3.0, 0.98)],
        scene_score=0.8,
    )
    second = analysis(
        tmp_path,
        "b",
        transcript_segments=[speech("这是第二段完整内容", 0.5, 3.2, 0.95)],
        scene_score=0.6,
    )
    planner = TimelinePlanner()

    timeline = planner.plan(
        [first, second],
        title="多素材样例",
        target_seconds=5.0,
    )

    assert timeline.actual_duration_seconds <= 5.0
    assert {clip.material_id for clip in timeline.clips} == {"a", "b"}
    assert timeline.clips[0].material_id == "a"
    assert timeline.clips[0].reason.startswith("hook:")
    assert all("嗯" not in cue.text for cue in timeline.captions)
    assert {cue.material_id for cue in timeline.captions} == {"a", "b"}
    assert timeline.captions[0].start_seconds >= 0
    assert timeline.captions[-1].end_seconds <= timeline.actual_duration_seconds
    assert timeline.cover.material_id == timeline.clips[0].material_id


def test_planner_never_reuses_same_source_interval_and_caps_automatic_duration(tmp_path: Path):
    source = analysis(tmp_path, "only", duration=10)
    planner = TimelinePlanner(max_automatic_seconds=6)

    timeline = planner.plan([source], title="视觉片段", target_seconds=50)

    intervals = [(clip.source_start_seconds, clip.source_end_seconds) for clip in timeline.clips]
    assert len(intervals) == len(set(intervals))
    assert timeline.actual_duration_seconds <= 6
    assert all(clip.duration_seconds >= 0.3 for clip in timeline.clips)
    assert all(clip.duration_seconds <= 3.01 for clip in timeline.clips)
    assert all(
        clip.source_start_seconds >= 0.8
        for clip in timeline.clips
        if clip.reason.endswith("visual:opening_trimmed") or "opening_trimmed" in clip.reason
    )


def test_timeline_validator_rejects_source_bounds_and_timeline_gaps(tmp_path: Path):
    source = analysis(tmp_path, "a", duration=5)
    invalid = EditingTimeline(
        title="invalid",
        target_duration_seconds=5,
        actual_duration_seconds=5,
        clips=[
            TimelineClip(
                material_id="a",
                source_path=source.source_path,
                source_start_seconds=4,
                source_end_seconds=6,
                timeline_start_seconds=1,
                timeline_end_seconds=3,
                score=1,
                reason="invalid",
                has_audio=True,
            )
        ],
        captions=[],
        cover=None,
    )

    with pytest.raises(ValueError, match="source bounds|start at zero"):
        validate_timeline(invalid, [source])


def test_timeline_clip_model_rejects_non_positive_duration():
    with pytest.raises(ValidationError):
        TimelineClip(
            material_id="a",
            source_path="a.mp4",
            source_start_seconds=1,
            source_end_seconds=1,
            timeline_start_seconds=0,
            timeline_end_seconds=0,
            score=1,
            reason="invalid",
            has_audio=True,
        )


def test_reference_pacing_controls_clip_length_without_importing_reference(tmp_path: Path):
    source = analysis(
        tmp_path,
        "source",
        duration=8,
        transcript_segments=[speech("这是一段需要按照参考节奏拆开的完整讲解", 0, 7.5)],
    )
    reference = ReferenceVideoBrief(
        source_name="reference.mp4",
        duration_seconds=6,
        content_summary="参考片",
        style_summary="快节奏",
        structure_summary="四个短镜头",
        pacing=ReferencePacingProfile(
            average_scene_seconds=1.5,
            cuts_per_minute=40,
            preferred_clip_seconds=1.5,
            hook_window_seconds=1.5,
            pace="rapid",
        ),
        keep_patterns=["短镜头"],
        change_requirements=["素材原创"],
    )

    timeline = TimelinePlanner().plan(
        [source],
        title="参考节奏",
        target_seconds=5,
        reference_brief=reference,
    )

    assert timeline.engine == "reference_guided"
    assert all(clip.duration_seconds <= 1.51 for clip in timeline.clips)
    assert {clip.material_id for clip in timeline.clips} == {"source"}


def test_planner_applies_voiceover_decision_and_replaces_source_captions(tmp_path: Path):
    source = analysis(tmp_path, "stock", duration=6)
    voiceover = tmp_path / "voiceover.mp3"
    voiceover.write_bytes(b"voice")
    decision = AudioRoutingDecision(
        mode="narration",
        reason="未检测到有效人声，使用旁白建立完整叙事。",
        original_gain_db=-22,
        voiceover_path=str(voiceover),
        voiceover_gain_db=0,
        voice_type="zh_female_vv_uranus_bigtts",
        captions=[
            {
                "material_id": "voiceover",
                "text": "它只是看起来很无辜。",
                "start_seconds": 0,
                "end_seconds": 2,
                "source_start_seconds": 0,
                "source_end_seconds": 2,
            }
        ],
    )

    timeline = TimelinePlanner().plan(
        [source],
        title="库存萌宠素材",
        target_seconds=5,
        audio_decision=decision,
    )

    assert timeline.audio.mode == "narration"
    assert timeline.audio.voiceover_path == str(voiceover)
    assert timeline.audio.original_gain_db == -22
    assert timeline.audio.voice_type == "zh_female_vv_uranus_bigtts"
    assert [cue.text for cue in timeline.captions] == ["它只是看起来很无辜。"]
