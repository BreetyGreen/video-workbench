from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from app.adapters.ffmpeg import FfmpegAdapter, MediaToolNotFoundError


@pytest.fixture
def adapter(ffmpeg_bin: str, ffprobe_bin: str) -> FfmpegAdapter:
    return FfmpegAdapter(
        ffmpeg_bin=ffmpeg_bin,
        ffprobe_bin=ffprobe_bin,
    )


def test_probe_reports_video_and_audio(adapter: FfmpegAdapter, ffmpeg_fixture: Path):
    report = adapter.probe_media(ffmpeg_fixture)

    assert report.video_streams == 1
    assert report.audio_streams == 1
    assert report.duration_seconds > 1
    assert report.width == 320
    assert report.height == 240


def test_create_preview_normalizes_vertical_h264_video(
    adapter: FfmpegAdapter,
    ffmpeg_fixture: Path,
    tmp_path: Path,
):
    output = tmp_path / "preview.mp4"

    result = adapter.create_preview(ffmpeg_fixture, output)
    report = adapter.probe_media(output)

    assert result.output_path == output.resolve()
    assert output.exists()
    assert report.width == 1080
    assert report.height == 1920
    assert report.video_codec == "h264"
    assert report.audio_codec == "aac"
    assert Path(result.command[0]).name.lower() == "ffmpeg.exe"


def test_missing_binary_has_explicit_error(ffmpeg_fixture: Path):
    adapter = FfmpegAdapter(ffmpeg_bin="missing-ffmpeg", ffprobe_bin="missing-ffprobe")

    with pytest.raises(MediaToolNotFoundError, match="missing-ffprobe"):
        adapter.probe_media(ffmpeg_fixture)


def test_quality_scan_reports_warning_lists(adapter: FfmpegAdapter, ffmpeg_fixture: Path):
    report = adapter.scan_quality(ffmpeg_fixture)

    assert report.black_frame_warnings == []
    assert report.silence_warnings == []
    assert "blackdetect=d=0.5:pix_th=0.10" in report.command


def test_probe_uses_video_stream_duration_when_audio_is_longer(
    adapter: FfmpegAdapter,
    ffmpeg_bin: str,
    tmp_path: Path,
):
    source = tmp_path / "audio-tail.mp4"
    subprocess.run(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:r=30:d=1.033333",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=600:sample_rate=48000:d=1.05",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    report = adapter.probe_media(source)

    assert report.duration_seconds == 1.033
