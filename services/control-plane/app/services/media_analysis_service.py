from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.adapters.ffmpeg import FfmpegAdapter
from app.adapters.transcription import RoutedTranscriber, VolcanoBigASRTranscriber, WhisperTranscriber
from app.config import Settings
from app.schemas.editing import MediaAnalysis, TranscriptResult


class MediaAnalysisService:
    def __init__(
        self,
        settings: Settings,
        *,
        transcriber: WhisperTranscriber | RoutedTranscriber | None = None,
        ocr_reader: Callable[[Path], list[str]] | None = None,
    ):
        self.settings = settings
        self.ffmpeg = FfmpegAdapter(
            ffmpeg_bin=settings.ffmpeg_bin,
            ffprobe_bin=settings.ffprobe_bin,
        )
        if isinstance(transcriber, RoutedTranscriber):
            self.transcriber = transcriber
        else:
            preview = transcriber or WhisperTranscriber(
                model_name=settings.whisper_preview_model or settings.whisper_model,
                cache_dir=settings.model_dir,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
                cpu_threads=settings.whisper_cpu_threads,
            )
            quality = transcriber or WhisperTranscriber(
                model_name=settings.whisper_quality_model,
                cache_dir=settings.model_dir,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
                cpu_threads=settings.whisper_cpu_threads,
            )
            cloud = VolcanoBigASRTranscriber(
                api_key=settings.volcano_asr_api_key,
                app_key=settings.volcano_asr_app_key,
                access_key=settings.volcano_asr_access_key,
                resource_id=settings.volcano_asr_resource_id,
                endpoint=settings.volcano_asr_endpoint,
                timeout_seconds=settings.volcano_asr_timeout_seconds,
                ffmpeg_bin=settings.ffmpeg_bin,
            )
            self.transcriber = RoutedTranscriber(preview=preview, quality=quality, cloud=cloud)
        self._ocr_reader = ocr_reader
        self._ocr_engine: Any | None = None

    def _read_ocr(self, frame_path: Path) -> list[str]:
        if not self.settings.ocr_enabled:
            return []
        if self._ocr_reader is not None:
            return list(dict.fromkeys(item.strip() for item in self._ocr_reader(frame_path) if item.strip()))
        if self._ocr_engine is None:
            from rapidocr import RapidOCR

            self._ocr_engine = RapidOCR()
        result = self._ocr_engine(str(frame_path))
        texts: list[str] = []
        if hasattr(result, "txts"):
            texts = list(getattr(result, "txts") or [])
        elif isinstance(result, tuple) and result:
            rows = result[0] or []
            texts = [str(row[1]) for row in rows if len(row) > 1]
        return list(dict.fromkeys(str(item).strip() for item in texts if str(item).strip()))

    def analyze(
        self,
        source: Path,
        *,
        material_id: str,
        output_dir: Path,
        quality_profile: str = "production",
        cloud_processing_allowed: bool = False,
    ) -> MediaAnalysis:
        resolved = source.resolve()
        probe = self.ffmpeg.probe_media(resolved)
        if probe.video_streams == 0 or not probe.width or not probe.height:
            raise ValueError("Media analysis requires a video stream")
        warnings: list[str] = []
        transcript = TranscriptResult(duration_seconds=probe.duration_seconds)
        if probe.audio_streams and self.settings.transcription_enabled:
            try:
                transcript = self.transcriber.transcribe(
                    resolved,
                    quality_profile=quality_profile,
                    cloud_processing_allowed=cloud_processing_allowed,
                )
            except Exception as error:
                warnings.append(f"transcription_failed:{type(error).__name__}")

        try:
            scenes = self.ffmpeg.detect_scenes(resolved, threshold=self.settings.scene_threshold)
        except Exception as error:
            warnings.append(f"scene_detection_failed:{type(error).__name__}")
            scenes = []
        try:
            silences = self.ffmpeg.detect_silence(
                resolved,
                threshold_db=self.settings.silence_threshold_db,
                minimum_seconds=self.settings.silence_minimum_seconds,
            )
        except Exception as error:
            warnings.append(f"silence_detection_failed:{type(error).__name__}")
            silences = []

        evidence_dir = output_dir.resolve() / material_id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        timestamps = [0.1, probe.duration_seconds / 2]
        timestamps.extend(scene.start_seconds + min(0.12, (scene.end_seconds - scene.start_seconds) / 2) for scene in scenes)
        normalized = []
        for timestamp in sorted(timestamps):
            bounded = min(max(0, timestamp), max(0, probe.duration_seconds - 0.05))
            if not any(abs(bounded - existing) < 0.08 for existing in normalized):
                normalized.append(bounded)
            if len(normalized) >= max(1, self.settings.keyframe_limit):
                break

        frames = []
        for index, timestamp in enumerate(normalized):
            try:
                frame_path = self.ffmpeg.extract_frame(
                    resolved,
                    timestamp,
                    evidence_dir / f"frame-{index:03d}.jpg",
                )
                frame = self.ffmpeg.measure_frame(frame_path, timestamp_seconds=timestamp)
                frame.ocr_texts = self._read_ocr(frame_path)
                frames.append(frame)
            except Exception as error:
                warnings.append(f"frame_analysis_failed:{index}:{type(error).__name__}")

        return MediaAnalysis(
            material_id=material_id,
            source_path=str(resolved),
            duration_seconds=probe.duration_seconds,
            width=probe.width,
            height=probe.height,
            has_audio=probe.audio_streams > 0,
            transcript=transcript,
            scenes=scenes,
            silences=silences,
            frames=frames,
            warnings=warnings,
        )
