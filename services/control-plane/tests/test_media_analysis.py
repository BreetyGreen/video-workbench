from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.adapters.ffmpeg import FfmpegAdapter
from app.adapters.transcription import RoutedTranscriber, VolcanoBigASRTranscriber, WhisperTranscriber
from app.config import Settings
from app.schemas.editing import TranscriptResult, TranscriptSegment
from app.services.media_analysis_service import MediaAnalysisService


def make_scene_fixture(path: Path, ffmpeg_bin: str) -> Path:
    subprocess.run(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=320x240:r=25:d=1",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:r=25:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000:d=2",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-map",
            "2:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return path


class FakeWord:
    def __init__(self, word: str, start: float, end: float, probability: float):
        self.word = word
        self.start = start
        self.end = end
        self.probability = probability


class FakeSegment:
    id = 0
    text = " 你好，世界 "
    start = 0.2
    end = 1.5
    avg_logprob = -0.1
    words = [FakeWord("你好", 0.2, 0.7, 0.95), FakeWord("世界", 0.8, 1.5, 0.92)]


class FakeWhisperModel:
    def transcribe(self, path: str, **kwargs):
        assert Path(path).is_file()
        assert kwargs["word_timestamps"] is True
        assert kwargs["vad_filter"] is True
        return iter([FakeSegment()]), SimpleNamespace(
            language="zh",
            language_probability=0.98,
            duration=2.0,
        )


def test_whisper_transcriber_returns_typed_word_timestamps(tmp_path: Path):
    source = tmp_path / "voice.wav"
    source.write_bytes(b"fake-audio")
    transcriber = WhisperTranscriber(
        model_name="small",
        cache_dir=tmp_path / "models",
        model_factory=lambda *args, **kwargs: FakeWhisperModel(),
    )

    result = transcriber.transcribe(source)

    assert result.language == "zh"
    assert result.language_probability == 0.98
    assert result.segments[0].text == "你好，世界"
    assert result.segments[0].words[1].start_seconds == 0.8
    assert result.segments[0].words[1].probability == 0.92


def test_ffmpeg_detects_scene_silence_and_measures_frame(
    tmp_path: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
):
    source = make_scene_fixture(tmp_path / "scenes.mp4", ffmpeg_bin)
    adapter = FfmpegAdapter(ffmpeg_bin=ffmpeg_bin, ffprobe_bin=ffprobe_bin)

    scenes = adapter.detect_scenes(source, threshold=0.2)
    silences = adapter.detect_silence(source, minimum_seconds=0.5)
    frame_path = adapter.extract_frame(source, 1.4, tmp_path / "frame.jpg")
    frame = adapter.measure_frame(frame_path, timestamp_seconds=1.4)

    assert any(0.7 <= scene.start_seconds <= 1.3 for scene in scenes)
    assert silences[0].start_seconds <= 0.1
    assert silences[0].end_seconds >= 1.8
    assert frame.width == 320
    assert frame.height == 240
    assert frame.brightness > 0
    assert frame.contrast >= 0
    assert frame.sharpness >= 0


def test_media_analysis_combines_probe_transcript_scenes_frames_and_ocr(
    tmp_path: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
):
    source = make_scene_fixture(tmp_path / "analysis.mp4", ffmpeg_bin)
    settings = Settings(
        data_dir=tmp_path / "data",
        ffmpeg_bin=ffmpeg_bin,
        ffprobe_bin=ffprobe_bin,
        transcription_enabled=True,
        keyframe_limit=4,
    )
    transcriber = WhisperTranscriber(
        model_name="small",
        cache_dir=settings.model_dir,
        model_factory=lambda *args, **kwargs: FakeWhisperModel(),
    )
    service = MediaAnalysisService(
        settings,
        transcriber=transcriber,
        ocr_reader=lambda path: ["画面文字"],
    )

    analysis = service.analyze(source, material_id="material-1", output_dir=tmp_path / "evidence")

    assert analysis.material_id == "material-1"
    assert analysis.has_audio is True
    assert analysis.transcript.language == "zh"
    assert len(analysis.scenes) >= 1
    assert len(analysis.silences) >= 1
    assert len(analysis.frames) >= 2
    assert any(frame.ocr_texts == ["画面文字"] for frame in analysis.frames)
    assert all(Path(frame.image_path).is_file() for frame in analysis.frames)


class FakeTranscriptProvider:
    def __init__(self, provider: str, *, error: Exception | None = None):
        self.provider = provider
        self.error = error
        self.calls = 0

    @property
    def configured(self) -> bool:
        return True

    def transcribe(self, source: Path) -> TranscriptResult:
        self.calls += 1
        if self.error:
            raise self.error
        return TranscriptResult(
            language="zh",
            duration_seconds=1,
            provider=self.provider,
            model=f"{self.provider}-model",
            segments=[
                TranscriptSegment(
                    text=self.provider,
                    start_seconds=0,
                    end_seconds=1,
                    confidence=0.9,
                )
            ],
        )


def test_routed_transcriber_uses_cloud_only_for_consented_production(tmp_path: Path):
    source = tmp_path / "voice.wav"
    source.write_bytes(b"audio")
    preview = FakeTranscriptProvider("preview")
    quality = FakeTranscriptProvider("quality")
    cloud = FakeTranscriptProvider("cloud")
    router = RoutedTranscriber(preview=preview, quality=quality, cloud=cloud)

    cloud_result = router.transcribe(
        source,
        quality_profile="production",
        cloud_processing_allowed=True,
    )
    private_result = router.transcribe(
        source,
        quality_profile="local_privacy",
        cloud_processing_allowed=True,
    )

    assert cloud_result.provider == "cloud"
    assert cloud_result.quality_profile == "production"
    assert private_result.provider == "quality"
    assert private_result.quality_profile == "local_privacy"
    assert cloud.calls == 1
    assert quality.calls == 1


def test_routed_transcriber_records_fallback_to_preview(tmp_path: Path):
    source = tmp_path / "voice.wav"
    source.write_bytes(b"audio")
    preview = FakeTranscriptProvider("preview")
    quality = FakeTranscriptProvider("quality", error=RuntimeError("quality unavailable"))
    cloud = FakeTranscriptProvider("cloud", error=TimeoutError("cloud timeout"))
    router = RoutedTranscriber(preview=preview, quality=quality, cloud=cloud)

    result = router.transcribe(
        source,
        quality_profile="production",
        cloud_processing_allowed=True,
    )

    assert result.provider == "preview"
    assert result.quality_profile == "production"
    assert result.fallback_reason == "cloud:TimeoutError;quality:RuntimeError"


def test_volcano_bigasr_parses_official_utterance_and_word_timestamps(tmp_path: Path):
    source = tmp_path / "voice.wav"
    source.write_bytes(b"audio")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "big-asr-key"
        assert request.headers["x-api-resource-id"] == "volc.bigasr.auc_turbo"
        payload = __import__("json").loads(request.content)
        assert payload["audio"]["data"]
        return httpx.Response(
            200,
            headers={"X-Api-Status-Code": "20000000", "X-Tt-Logid": "log-1"},
            json={
                "audio_info": {"duration": 2499},
                "result": {
                    "text": "关闭透传。",
                    "utterances": [
                        {
                            "start_time": 450,
                            "end_time": 1530,
                            "text": "关闭透传。",
                            "words": [
                                {"start_time": 450, "end_time": 770, "text": "关", "confidence": 0.95},
                                {"start_time": 770, "end_time": 970, "text": "闭", "confidence": 0.92},
                            ],
                        }
                    ],
                },
            },
        )

    transcriber = VolcanoBigASRTranscriber(
        api_key="big-asr-key",
        transport=httpx.MockTransport(handler),
    )

    result = transcriber.transcribe(source)

    assert result.provider == "volcano_bigasr"
    assert result.model == "volc.bigasr.auc_turbo"
    assert result.duration_seconds == 2.499
    assert result.segments[0].start_seconds == 0.45
    assert result.segments[0].words[1].end_seconds == 0.97


def test_volcano_bigasr_treats_normal_silence_as_valid_empty_transcript(tmp_path: Path):
    source = tmp_path / "ambient.wav"
    source.write_bytes(b"audio")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "X-Api-Status-Code": "20000003",
                "X-Api-Message": "[Normal silence audio] no valid speech in audio",
            },
            json={},
        )

    result = VolcanoBigASRTranscriber(
        api_key="big-asr-key",
        transport=httpx.MockTransport(handler),
    ).transcribe(source)

    assert result.provider == "volcano_bigasr"
    assert result.model == "volc.bigasr.auc_turbo"
    assert result.segments == []
