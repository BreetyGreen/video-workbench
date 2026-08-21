from __future__ import annotations

from pathlib import Path

from app.adapters.ffmpeg import FfmpegAdapter
from app.config import Settings
from app.schemas.editing import CaptionCue, EditingTimeline, MediaAnalysis, TimelineClip, TranscriptResult
from app.services.quality_gate_service import QualityGateService


def make_timeline(source: Path, duration: float = 2) -> EditingTimeline:
    return EditingTimeline(
        title="quality fixture",
        target_duration_seconds=duration,
        actual_duration_seconds=duration,
        clips=[
            TimelineClip(
                material_id="source",
                source_path=str(source),
                source_start_seconds=0,
                source_end_seconds=duration,
                timeline_start_seconds=0,
                timeline_end_seconds=duration,
                score=8,
                reason="hook:visual:opening",
                has_audio=True,
            )
        ],
    )


def make_analysis(source: Path, duration: float = 2) -> MediaAnalysis:
    return MediaAnalysis(
        material_id="source",
        source_path=str(source),
        duration_seconds=duration,
        width=320,
        height=240,
        has_audio=True,
        transcript=TranscriptResult(duration_seconds=duration),
    )


def test_quality_gate_passes_rendered_vertical_fixture(
    tmp_path: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
    ffmpeg_fixture: Path,
):
    settings = Settings(
        data_dir=tmp_path / "data",
        ffmpeg_bin=ffmpeg_bin,
        ffprobe_bin=ffprobe_bin,
    )
    preview = tmp_path / "preview.mp4"
    FfmpegAdapter(ffmpeg_bin=ffmpeg_bin, ffprobe_bin=ffprobe_bin).create_preview(
        ffmpeg_fixture,
        preview,
        max_duration_seconds=2,
    )
    captions = tmp_path / "captions.srt"
    draft = tmp_path / "draft.zip"
    cover = tmp_path / "cover.jpg"
    captions.write_text("", encoding="utf-8")
    draft.write_bytes(b"draft")
    cover.write_bytes(b"cover")

    report = QualityGateService(settings).evaluate(
        preview_path=preview,
        timeline=make_timeline(ffmpeg_fixture),
        analyses=[make_analysis(ffmpeg_fixture)],
        captions_path=captions,
        draft_path=draft,
        cover_path=cover,
    )

    assert report.status == "pass"
    assert report.blocking_failures == []
    assert all(gate.status == "pass" for gate in report.gates if gate.blocking)


def test_quality_gate_fails_wrong_canvas(
    tmp_path: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
    ffmpeg_fixture: Path,
):
    settings = Settings(
        data_dir=tmp_path / "data",
        ffmpeg_bin=ffmpeg_bin,
        ffprobe_bin=ffprobe_bin,
    )
    captions = tmp_path / "captions.srt"
    draft = tmp_path / "draft.zip"
    cover = tmp_path / "cover.jpg"
    captions.write_text("", encoding="utf-8")
    draft.write_bytes(b"draft")
    cover.write_bytes(b"cover")

    report = QualityGateService(settings).evaluate(
        preview_path=ffmpeg_fixture,
        timeline=make_timeline(ffmpeg_fixture),
        analyses=[make_analysis(ffmpeg_fixture)],
        captions_path=captions,
        draft_path=draft,
        cover_path=cover,
    )

    assert report.status == "fail"
    assert "canvas" in report.blocking_failures


def test_quality_gate_blocks_incomplete_narration_caption_coverage(
    tmp_path: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
    ffmpeg_fixture: Path,
):
    settings = Settings(data_dir=tmp_path / "data", ffmpeg_bin=ffmpeg_bin, ffprobe_bin=ffprobe_bin)
    preview = tmp_path / "preview.mp4"
    FfmpegAdapter(ffmpeg_bin=ffmpeg_bin, ffprobe_bin=ffprobe_bin).create_preview(ffmpeg_fixture, preview, max_duration_seconds=2)
    captions = tmp_path / "captions.srt"
    captions.write_text("partial", encoding="utf-8")
    draft = tmp_path / "draft.zip"
    draft.write_bytes(b"draft")
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover")
    timeline = make_timeline(ffmpeg_fixture)
    timeline.audio.voiceover_path = str(tmp_path / "voice.mp3")
    timeline.audio.voiceover_duration_seconds = 2
    timeline.captions = [
        CaptionCue(
            material_id="voiceover",
            text="只有第一段",
            start_seconds=0,
            end_seconds=0.5,
            source_start_seconds=0,
            source_end_seconds=0.5,
        )
    ]

    report = QualityGateService(settings).evaluate(
        preview_path=preview,
        timeline=timeline,
        analyses=[make_analysis(ffmpeg_fixture)],
        captions_path=captions,
        draft_path=draft,
        cover_path=cover,
    )

    gate = next(item for item in report.gates if item.name == "narration_coverage")
    assert gate.status == "fail"
    assert gate.evidence["coverage_percent"] == 25
    assert "narration_coverage" in report.blocking_failures


def test_quality_gate_blocks_voiceover_that_runs_past_the_video(
    tmp_path: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
    ffmpeg_fixture: Path,
):
    settings = Settings(data_dir=tmp_path / "data", ffmpeg_bin=ffmpeg_bin, ffprobe_bin=ffprobe_bin)
    preview = tmp_path / "preview.mp4"
    FfmpegAdapter(ffmpeg_bin=ffmpeg_bin, ffprobe_bin=ffprobe_bin).create_preview(ffmpeg_fixture, preview, max_duration_seconds=2)
    captions = tmp_path / "captions.srt"
    captions.write_text("complete", encoding="utf-8")
    draft = tmp_path / "draft.zip"
    draft.write_bytes(b"draft")
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover")
    timeline = make_timeline(ffmpeg_fixture)
    timeline.audio.mode = "narration"
    timeline.audio.voiceover_path = str(tmp_path / "voice.mp3")
    timeline.audio.voiceover_duration_seconds = 3.2
    timeline.captions = [
        CaptionCue(
            material_id="voiceover",
            text="完整字幕",
            start_seconds=0,
            end_seconds=2,
            source_start_seconds=0,
            source_end_seconds=2,
        )
    ]

    report = QualityGateService(settings).evaluate(
        preview_path=preview,
        timeline=timeline,
        analyses=[make_analysis(ffmpeg_fixture)],
        captions_path=captions,
        draft_path=draft,
        cover_path=cover,
    )

    gate = next(item for item in report.gates if item.name == "voiceover_fit")
    assert gate.status == "fail"
    assert gate.evidence["overrun_seconds"] == 1.2
    assert "voiceover_fit" in report.blocking_failures
