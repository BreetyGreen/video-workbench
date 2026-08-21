from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image

from app.config import Settings
from app.schemas.editing import CaptionCue, CoverPlan, EditingTimeline, TimelineClip
from app.services.render_service import RenderService


def make_video(
    path: Path,
    ffmpeg_bin: str,
    *,
    size: str,
    color: str,
    with_audio: bool,
) -> Path:
    command = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s={size}:r=25:d=2",
    ]
    if with_audio:
        command.extend(["-f", "lavfi", "-i", "sine=frequency=700:sample_rate=48000:d=2"])
    command.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p"])
    if with_audio:
        command.extend(["-c:a", "aac", "-shortest"])
    command.append(str(path))
    subprocess.run(command, check=True, capture_output=True, text=True)
    return path


def test_renderer_creates_vertical_multisource_video_captions_cover_and_report(
    tmp_path: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
):
    landscape = make_video(
        tmp_path / "landscape.mp4",
        ffmpeg_bin,
        size="640x360",
        color="red",
        with_audio=True,
    )
    vertical = make_video(
        tmp_path / "vertical.mp4",
        ffmpeg_bin,
        size="360x640",
        color="blue",
        with_audio=False,
    )
    timeline = EditingTimeline(
        title="真实多素材剪辑",
        target_duration_seconds=2,
        actual_duration_seconds=2,
        clips=[
            TimelineClip(
                material_id="a",
                source_path=str(landscape),
                source_start_seconds=0.2,
                source_end_seconds=1.2,
                timeline_start_seconds=0,
                timeline_end_seconds=1,
                score=8,
                reason="hook:speech",
                has_audio=True,
            ),
            TimelineClip(
                material_id="b",
                source_path=str(vertical),
                source_start_seconds=0.5,
                source_end_seconds=1.5,
                timeline_start_seconds=1,
                timeline_end_seconds=2,
                score=6,
                reason="visual:scene_change",
                has_audio=False,
            ),
        ],
        captions=[
            CaptionCue(
                material_id="a",
                text="先看最后的效果",
                start_seconds=0.1,
                end_seconds=0.9,
                source_start_seconds=0.3,
                source_end_seconds=1.1,
            ),
            CaptionCue(
                material_id="b",
                text="第二段画面",
                start_seconds=1.1,
                end_seconds=1.9,
                source_start_seconds=0.6,
                source_end_seconds=1.4,
            ),
        ],
        cover=CoverPlan(
            material_id="a",
            source_path=str(landscape),
            source_timestamp_seconds=0.6,
            title="真实多素材剪辑",
        ),
        source_count=2,
    )
    settings = Settings(
        data_dir=tmp_path / "data",
        ffmpeg_bin=ffmpeg_bin,
        ffprobe_bin=ffprobe_bin,
        render_preset="ultrafast",
        render_crf=28,
    )

    artifacts = RenderService(settings).render(timeline, tmp_path / "render")

    assert artifacts.preview_path.is_file()
    assert artifacts.ass_path.is_file()
    assert artifacts.srt_path.is_file()
    assert artifacts.cover_path.is_file()
    assert artifacts.report_path.is_file()
    assert "先看最后的效果" in artifacts.ass_path.read_text(encoding="utf-8-sig")
    probe = RenderService(settings).ffmpeg.probe_media(artifacts.preview_path)
    assert (probe.width, probe.height) == (1080, 1920)
    assert probe.video_streams == 1
    assert probe.audio_streams == 1
    assert 1.8 <= probe.duration_seconds <= 2.2
    with Image.open(artifacts.cover_path) as cover:
        assert cover.size == (1080, 1920)
    report = json.loads(artifacts.report_path.read_text(encoding="utf-8"))
    assert report["clip_count"] == 2
    assert report["source_count"] == 2
    assert report["caption_count"] == 2
    assert report["audio"]["target_lufs"] == -14


def test_renderer_mixes_uploaded_bgm_at_low_gain(
    tmp_path: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
):
    video = make_video(
        tmp_path / "video.mp4",
        ffmpeg_bin,
        size="320x240",
        color="green",
        with_audio=True,
    )
    bgm = tmp_path / "music.wav"
    subprocess.run(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:sample_rate=48000:d=1",
            str(bgm),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    timeline = EditingTimeline(
        title="BGM",
        target_duration_seconds=1,
        actual_duration_seconds=1,
        clips=[
            TimelineClip(
                material_id="a",
                source_path=str(video),
                source_start_seconds=0,
                source_end_seconds=1,
                timeline_start_seconds=0,
                timeline_end_seconds=1,
                score=1,
                reason="hook:test",
                has_audio=True,
            )
        ],
        captions=[],
        cover=None,
        audio={"bgm_path": str(bgm), "bgm_gain_db": -18},
    )
    settings = Settings(
        data_dir=tmp_path / "data",
        ffmpeg_bin=ffmpeg_bin,
        ffprobe_bin=ffprobe_bin,
        render_preset="ultrafast",
    )

    artifacts = RenderService(settings).render(timeline, tmp_path / "mix")

    report = json.loads(artifacts.report_path.read_text(encoding="utf-8"))
    assert report["audio"]["bgm_used"] is True
    assert report["audio"]["bgm_gain_db"] == -18
    assert RenderService(settings).ffmpeg.probe_media(artifacts.preview_path).audio_streams == 1


def test_renderer_mixes_voiceover_as_independent_track(
    tmp_path: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
):
    video = make_video(
        tmp_path / "video.mp4",
        ffmpeg_bin,
        size="320x240",
        color="yellow",
        with_audio=True,
    )
    voiceover = tmp_path / "voiceover.wav"
    subprocess.run(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:d=1",
            str(voiceover),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    timeline = EditingTimeline(
        title="旁白混音",
        target_duration_seconds=1,
        actual_duration_seconds=1,
        clips=[
            TimelineClip(
                material_id="a",
                source_path=str(video),
                source_start_seconds=0,
                source_end_seconds=1,
                timeline_start_seconds=0,
                timeline_end_seconds=1,
                score=1,
                reason="hook:test",
                has_audio=True,
            )
        ],
        captions=[],
        cover=None,
        audio={
            "mode": "mixed",
            "original_gain_db": -10,
            "voiceover_path": str(voiceover),
            "voiceover_gain_db": 0,
            "voice_type": "zh_female_vv_uranus_bigtts",
            "decision_reason": "少量原声，旁白补充。",
        },
    )
    settings = Settings(
        data_dir=tmp_path / "data",
        ffmpeg_bin=ffmpeg_bin,
        ffprobe_bin=ffprobe_bin,
        render_preset="ultrafast",
    )

    artifacts = RenderService(settings).render(timeline, tmp_path / "voice-mix")

    report = json.loads(artifacts.report_path.read_text(encoding="utf-8"))
    assert report["audio"]["mode"] == "mixed"
    assert report["audio"]["voiceover_used"] is True
    assert report["audio"]["voice_type"] == "zh_female_vv_uranus_bigtts"
    assert report["audio"]["original_gain_db"] == -10
    assert RenderService(settings).ffmpeg.probe_media(artifacts.preview_path).audio_streams == 1
