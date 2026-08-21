from __future__ import annotations

import math
import base64
import subprocess
import tempfile
from copy import deepcopy
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.schemas.editing import TranscriptResult, TranscriptSegment, TranscriptWord


class WhisperTranscriber:
    def __init__(
        self,
        *,
        model_name: str,
        cache_dir: Path,
        device: str = "cpu",
        compute_type: str = "int8",
        cpu_threads: int = 0,
        model_factory: Callable[..., Any] | None = None,
    ):
        self.model_name = model_name
        self.cache_dir = cache_dir.resolve()
        self.device = device
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self.model_factory = model_factory
        self._model: Any | None = None

    def _load_model(self):
        if self._model is not None:
            return self._model
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        factory = self.model_factory
        if factory is None:
            from faster_whisper import WhisperModel

            factory = WhisperModel
        kwargs: dict[str, object] = {
            "device": self.device,
            "compute_type": self.compute_type,
            "download_root": str(self.cache_dir),
        }
        if self.cpu_threads > 0:
            kwargs["cpu_threads"] = self.cpu_threads
        self._model = factory(self.model_name, **kwargs)
        return self._model

    def transcribe(self, source: Path) -> TranscriptResult:
        resolved = source.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        segments, info = self._load_model().transcribe(
            str(resolved),
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            word_timestamps=True,
            condition_on_previous_text=False,
        )
        converted = []
        for segment in segments:
            words = []
            for word in getattr(segment, "words", None) or []:
                start = max(0.0, float(word.start))
                end = max(start + 0.001, float(word.end))
                probability = float(getattr(word, "probability", 0) or 0)
                words.append(
                    TranscriptWord(
                        text=str(word.word).strip(),
                        start_seconds=start,
                        end_seconds=end,
                        probability=min(1.0, max(0.0, probability)),
                    )
                )
            avg_logprob = float(getattr(segment, "avg_logprob", -10) or -10)
            confidence = math.exp(avg_logprob) if avg_logprob < 0 else 1.0
            converted.append(
                TranscriptSegment(
                    text=str(segment.text).strip(),
                    start_seconds=max(0.0, float(segment.start)),
                    end_seconds=max(float(segment.start) + 0.001, float(segment.end)),
                    confidence=min(1.0, max(0.0, confidence)),
                    words=words,
                )
            )
        return TranscriptResult(
            language=str(getattr(info, "language", "") or ""),
            language_probability=min(
                1.0,
                max(0.0, float(getattr(info, "language_probability", 0) or 0)),
            ),
            duration_seconds=max(0.0, float(getattr(info, "duration", 0) or 0)),
            provider="whisper",
            model=self.model_name,
            segments=converted,
        )


class VolcanoBigASRTranscriber:
    def __init__(
        self,
        *,
        api_key: str = "",
        app_key: str = "",
        access_key: str = "",
        resource_id: str = "volc.bigasr.auc_turbo",
        endpoint: str = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash",
        timeout_seconds: float = 180.0,
        ffmpeg_bin: str = "ffmpeg",
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key.strip()
        self.app_key = app_key.strip()
        self.access_key = access_key.strip()
        self.resource_id = resource_id.strip() or "volc.bigasr.auc_turbo"
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.ffmpeg_bin = ffmpeg_bin
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.api_key or (self.app_key and self.access_key))

    def _headers(self) -> dict[str, str]:
        headers = {
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": str(uuid4()),
            "X-Api-Sequence": "-1",
        }
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        else:
            headers["X-Api-App-Key"] = self.app_key
            headers["X-Api-Access-Key"] = self.access_key
        return headers

    def _read_audio(self, source: Path) -> bytes:
        if source.suffix.lower() in {".wav", ".mp3", ".ogg", ".opus"}:
            payload = source.read_bytes()
        else:
            with tempfile.TemporaryDirectory(prefix="video-workbench-asr-") as temp_dir:
                output = Path(temp_dir) / "speech.wav"
                completed = subprocess.run(
                    [
                        self.ffmpeg_bin,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-i",
                        str(source),
                        "-vn",
                        "-ac",
                        "1",
                        "-ar",
                        "16000",
                        "-c:a",
                        "pcm_s16le",
                        "-y",
                        str(output),
                    ],
                    capture_output=True,
                    text=True,
                )
                if completed.returncode != 0 or not output.is_file():
                    raise RuntimeError("Failed to extract audio for Volcano BigASR")
                payload = output.read_bytes()
        if len(payload) > 100 * 1024 * 1024:
            raise ValueError("Volcano BigASR synchronous input exceeds 100 MB")
        return payload

    def transcribe(self, source: Path) -> TranscriptResult:
        resolved = source.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        if not self.configured:
            raise RuntimeError("Volcano BigASR is not configured")
        audio = base64.b64encode(self._read_audio(resolved)).decode("ascii")
        payload = {
            "user": {"uid": self.app_key or "video-workbench"},
            "audio": {"data": audio},
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "enable_ddc": True,
            },
        }
        with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
            response = client.post(self.endpoint, headers=self._headers(), json=payload)
        response.raise_for_status()
        status_code = response.headers.get("X-Api-Status-Code", "")
        if status_code == "20000003":
            return TranscriptResult(
                provider="volcano_bigasr",
                model=self.resource_id,
                segments=[],
            )
        if status_code != "20000000":
            message = response.headers.get("X-Api-Message", "unknown error")
            raise RuntimeError(f"Volcano BigASR failed ({status_code}): {message}")
        body = response.json()
        result = body.get("result") or {}
        utterances = result.get("utterances") or []
        segments: list[TranscriptSegment] = []
        for utterance in utterances:
            words = [
                TranscriptWord(
                    text=str(word.get("text", "")).strip(),
                    start_seconds=max(0, float(word.get("start_time", 0)) / 1000),
                    end_seconds=max(
                        float(word.get("start_time", 0)) / 1000 + 0.001,
                        float(word.get("end_time", 0)) / 1000,
                    ),
                    probability=min(1, max(0, float(word.get("confidence", 0) or 0))),
                )
                for word in utterance.get("words") or []
                if str(word.get("text", "")).strip()
            ]
            confidences = [word.probability for word in words if word.probability > 0]
            start = max(0, float(utterance.get("start_time", 0)) / 1000)
            end = max(start + 0.001, float(utterance.get("end_time", 0)) / 1000)
            segments.append(
                TranscriptSegment(
                    text=str(utterance.get("text", "")).strip(),
                    start_seconds=start,
                    end_seconds=end,
                    confidence=sum(confidences) / len(confidences) if confidences else 0,
                    words=words,
                )
            )
        duration = float((body.get("audio_info") or {}).get("duration", 0) or 0) / 1000
        if not segments and str(result.get("text", "")).strip() and duration > 0:
            segments.append(
                TranscriptSegment(
                    text=str(result["text"]).strip(),
                    start_seconds=0,
                    end_seconds=duration,
                )
            )
        return TranscriptResult(
            language="zh",
            duration_seconds=duration,
            provider="volcano_bigasr",
            model=self.resource_id,
            segments=segments,
        )


class RoutedTranscriber:
    def __init__(self, *, preview: Any, quality: Any, cloud: Any | None = None):
        self.preview = preview
        self.quality = quality
        self.cloud = cloud

    @staticmethod
    def _with_route(
        result: TranscriptResult,
        *,
        quality_profile: str,
        fallback_reason: str = "",
    ) -> TranscriptResult:
        routed = deepcopy(result)
        routed.quality_profile = quality_profile
        routed.fallback_reason = fallback_reason
        return routed

    def transcribe(
        self,
        source: Path,
        *,
        quality_profile: str,
        cloud_processing_allowed: bool,
    ) -> TranscriptResult:
        if quality_profile == "fast_preview":
            return self._with_route(
                self.preview.transcribe(source),
                quality_profile=quality_profile,
            )

        failures: list[str] = []
        if quality_profile == "production" and cloud_processing_allowed:
            if self.cloud is not None and bool(getattr(self.cloud, "configured", False)):
                try:
                    return self._with_route(
                        self.cloud.transcribe(source),
                        quality_profile=quality_profile,
                    )
                except Exception as error:
                    failures.append(f"cloud:{type(error).__name__}")
            else:
                failures.append("cloud:not_configured")
        elif quality_profile == "production":
            failures.append("cloud:not_allowed")

        try:
            return self._with_route(
                self.quality.transcribe(source),
                quality_profile=quality_profile,
                fallback_reason=";".join(failures),
            )
        except Exception as error:
            failures.append(f"quality:{type(error).__name__}")
            return self._with_route(
                self.preview.transcribe(source),
                quality_profile=quality_profile,
                fallback_reason=";".join(failures),
            )
