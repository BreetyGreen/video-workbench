"""Alibaba DashScope speech adapters: Paraformer file transcription and Qwen TTS.

Both mirror the Volcano adapters' interfaces so the routed transcriber and the
pipeline can swap providers by configuration alone:

- ``DashScopeParaformerTranscriber.transcribe(path) -> TranscriptResult`` uploads a
  compact mono audio extract to DashScope's temporary storage (48 h, private),
  submits an async ``paraformer-v2`` job, polls it, and converts sentences and
  word timestamps.
- ``DashScopeTTSClient.synthesize(text, output, voice_type=...) -> TTSResult`` calls
  ``qwen3-tts-flash`` (or ``qwen-tts``), downloads the returned audio and stores
  it at ``output`` (transcoded to MP3 when FFmpeg is available).
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx

from app.adapters.volcano_tts import TTSResult
from app.schemas.editing import TranscriptResult, TranscriptSegment, TranscriptWord

DASHSCOPE_TTS_VOICES = ("Cherry", "Serena", "Ethan", "Chelsea", "Dylan", "Jada", "Sunny")
_NO_SPEECH = "NO_VALID_FRAGMENT"


class DashScopeParaformerTranscriber:
    provider_name = "dashscope_paraformer"

    def __init__(self, *, api_key: str = "", base_url: str = "", model: str = "paraformer-v2",
                 timeout_seconds: float = 900.0, poll_seconds: float = 3.0, ffmpeg_bin: str = "ffmpeg",
                 transport: httpx.BaseTransport | None = None):
        self.api_key = api_key.strip()
        self.base_url = base_url.strip().rstrip("/")
        self.model = model.strip() or "paraformer-v2"
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds
        self.ffmpeg_bin = ffmpeg_bin
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _extract_audio(self, source: Path, target: Path) -> Path:
        completed = subprocess.run(
            [self.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-i", str(source), "-vn", "-ac", "1",
             "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k", "-y", str(target)],
            capture_output=True, text=True, timeout=1800)
        if completed.returncode != 0 or not target.is_file():
            raise RuntimeError("Failed to extract audio for DashScope Paraformer")
        return target

    def _upload(self, client: httpx.Client, audio: Path) -> str:
        policy = client.get(f"{self.base_url}/uploads", params={"action": "getPolicy", "model": self.model},
                            headers=self._headers())
        policy.raise_for_status()
        data = policy.json().get("data") or {}
        for field in ("policy", "signature", "upload_dir", "upload_host", "oss_access_key_id"):
            if not data.get(field):
                raise RuntimeError(f"DashScope upload policy missing {field}")
        key = f"{data['upload_dir']}/{uuid4().hex}-{audio.name}"
        form = {
            "OSSAccessKeyId": data["oss_access_key_id"],
            "Signature": data["signature"],
            "policy": data["policy"],
            "key": key,
            "x-oss-object-acl": data.get("x_oss_object_acl", "private"),
            "x-oss-forbid-overwrite": data.get("x_oss_forbid_overwrite", "true"),
            "success_action_status": "200",
        }
        with audio.open("rb") as handle:
            upload = client.post(data["upload_host"], data=form, files={"file": (audio.name, handle, "audio/mpeg")})
        if upload.status_code not in (200, 204):
            raise RuntimeError(f"DashScope temporary upload failed ({upload.status_code})")
        return f"oss://{key}"

    @staticmethod
    def _to_result(payload: dict, *, model: str) -> TranscriptResult:
        segments: list[TranscriptSegment] = []
        duration = 0.0
        for transcript in payload.get("transcripts") or []:
            duration = max(duration, float(transcript.get("content_duration_in_milliseconds", 0) or 0) / 1000)
            for sentence in transcript.get("sentences") or []:
                words = [
                    TranscriptWord(
                        text=str(word.get("text", "")).strip(),
                        start_seconds=max(0.0, float(word.get("begin_time", 0) or 0) / 1000),
                        end_seconds=max(float(word.get("begin_time", 0) or 0) / 1000 + 0.001,
                                        float(word.get("end_time", 0) or 0) / 1000),
                    )
                    for word in sentence.get("words") or []
                    if str(word.get("text", "")).strip()
                ]
                start = max(0.0, float(sentence.get("begin_time", 0) or 0) / 1000)
                end = max(start + 0.001, float(sentence.get("end_time", 0) or 0) / 1000)
                text = str(sentence.get("text", "")).strip()
                if not text:
                    continue
                segments.append(TranscriptSegment(text=text, start_seconds=start, end_seconds=end, words=words))
        if segments:
            duration = max(duration, segments[-1].end_seconds)
        return TranscriptResult(language="zh", duration_seconds=duration, provider="dashscope_paraformer",
                                model=model, segments=segments)

    def transcribe(self, source: Path) -> TranscriptResult:
        resolved = source.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        if not self.configured:
            raise RuntimeError("DashScope Paraformer is not configured")
        with tempfile.TemporaryDirectory(prefix="video-workbench-dashscope-asr-") as temp_dir, \
                httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
            audio = self._extract_audio(resolved, Path(temp_dir) / "speech.mp3")
            oss_url = self._upload(client, audio)
            submit = client.post(
                f"{self.base_url}/services/audio/asr/transcription",
                headers={**self._headers(), "Content-Type": "application/json", "X-DashScope-Async": "enable",
                         "X-DashScope-OssResourceResolve": "enable"},
                json={"model": self.model, "input": {"file_urls": [oss_url]},
                      "parameters": {"language_hints": ["zh", "en"]}},
            )
            submit.raise_for_status()
            task_id = ((submit.json().get("output") or {}).get("task_id") or "").strip()
            if not task_id:
                raise RuntimeError("DashScope Paraformer returned no task id")
            deadline = time.monotonic() + self.timeout_seconds
            while True:
                status = client.get(f"{self.base_url}/tasks/{task_id}", headers=self._headers())
                status.raise_for_status()
                output = status.json().get("output") or {}
                state = str(output.get("task_status", "")).upper()
                if state == "SUCCEEDED":
                    break
                if state in {"FAILED", "CANCELED", "UNKNOWN"}:
                    detail = f"{output.get('code', '')} {output.get('message', '')}"
                    if _NO_SPEECH in detail.upper():
                        # No speech in the audio (typical for product B-roll): an empty transcript,
                        # never a failure that would trigger the slow local fallback.
                        return TranscriptResult(language="zh", duration_seconds=0.0,
                                                provider="dashscope_paraformer", model=self.model, segments=[])
                    raise RuntimeError(f"DashScope Paraformer task {state}: {detail[:200]}")
                if time.monotonic() > deadline:
                    raise RuntimeError("DashScope Paraformer task timed out")
                time.sleep(self.poll_seconds)
            results = output.get("results") or []
            first = results[0] if results else {}
            if not results or str(first.get("subtask_status", "")).upper() != "SUCCEEDED":
                if _NO_SPEECH in f"{first.get('code', '')} {first.get('message', '')}".upper():
                    return TranscriptResult(language="zh", duration_seconds=0.0,
                                            provider="dashscope_paraformer", model=self.model, segments=[])
                raise RuntimeError(f"DashScope Paraformer subtask failed: {str(results[:1])[:200]}")
            transcription = client.get(results[0]["transcription_url"])
            transcription.raise_for_status()
            return self._to_result(transcription.json(), model=self.model)


class DashScopeCosyVoiceClient:
    """CosyVoice v2 through the official DashScope SDK (WebSocket synthesis).

    Same ``synthesize`` contract as the other TTS clients. The SDK call is
    injectable so tests never open sockets.
    """

    provider_name = "dashscope"

    def __init__(self, *, api_key: str = "", model: str = "cosyvoice-v2", voice_type: str = "longxiaochun_v2",
                 speech_rate: float = 1.0, ffprobe_bin: str = "ffprobe", synthesizer_factory=None):
        self.api_key = api_key.strip()
        self.model = model.strip() or "cosyvoice-v2"
        self.voice_type = voice_type.strip() or "longxiaochun_v2"
        self.speech_rate = max(0.5, min(2.0, float(speech_rate or 1.0)))
        self.ffprobe_bin = ffprobe_bin
        self._factory = synthesizer_factory

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _synthesize_bytes(self, text: str, voice: str) -> bytes:
        if self._factory is not None:
            return self._factory(model=self.model, voice=voice, speech_rate=self.speech_rate).call(text)
        import dashscope
        from dashscope.audio.tts_v2 import SpeechSynthesizer

        dashscope.api_key = self.api_key
        return SpeechSynthesizer(model=self.model, voice=voice, speech_rate=self.speech_rate).call(text)

    def resolve_voice(self, voice_type: str | None) -> str:
        candidate = (voice_type or "").strip()
        # CosyVoice voices carry the model suffix (…_v2); anything else (Volcano/Qwen ids) uses the default.
        return candidate if candidate.endswith(("_v2", "_v3")) else self.voice_type

    def synthesize(self, text: str, output: Path, *, voice_type: str | None = None) -> TTSResult:
        normalized = text.strip()
        if not self.configured:
            raise RuntimeError("DashScope CosyVoice is not configured")
        if not normalized:
            raise ValueError("TTS text must not be empty")
        voice = self.resolve_voice(voice_type)
        payload = self._synthesize_bytes(normalized, voice)
        if not payload:
            raise RuntimeError("DashScope CosyVoice returned no audio")
        resolved = output.resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_bytes(payload)  # SDK default is MP3 22.05 kHz
        duration = DashScopeTTSClient._measured_duration_with(self.ffprobe_bin, resolved)
        return TTSResult(path=resolved, duration_seconds=duration, voice_type=voice, character_count=len(normalized))


class DashScopeTTSClient:
    provider_name = "dashscope"

    def __init__(self, *, api_key: str = "", base_url: str = "", model: str = "qwen3-tts-flash",
                 voice_type: str = "Cherry", instructions: str = "", timeout_seconds: float = 120.0,
                 ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe",
                 transport: httpx.BaseTransport | None = None):
        self.api_key = api_key.strip()
        self.base_url = base_url.strip().rstrip("/")
        self.model = model.strip() or "qwen3-tts-flash"
        self.voice_type = voice_type.strip() or "Cherry"
        self.instructions = instructions.strip()
        self.timeout_seconds = timeout_seconds
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url)

    @staticmethod
    def _measured_duration_with(ffprobe_bin: str, path: Path) -> float:
        try:
            completed = subprocess.run(
                [ffprobe_bin, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                capture_output=True, text=True, timeout=30)
            if completed.returncode != 0:
                return 0.0
            return max(0.0, float(json.loads(completed.stdout).get("format", {}).get("duration", 0) or 0))
        except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired):
            return 0.0

    def _measured_duration(self, path: Path) -> float:
        return self._measured_duration_with(self.ffprobe_bin, path)

    @staticmethod
    def _is_dashscope_voice(candidate: str) -> bool:
        # Preset voices, plus designed/cloned voices whose ids DashScope mints (qwen-tts-vd-…, qwen-tts-vc-…).
        return candidate in DASHSCOPE_TTS_VOICES or candidate.startswith(("qwen-tts-vd-", "qwen-tts-vc-"))

    def resolve_voice(self, voice_type: str | None) -> str:
        """Map any requested voice to a DashScope voice; foreign (Volcano) ids fall back to the configured default."""
        candidate = (voice_type or "").strip()
        if self._is_dashscope_voice(candidate):
            return candidate
        return self.voice_type if self._is_dashscope_voice(self.voice_type) else "Cherry"

    def synthesize(self, text: str, output: Path, *, voice_type: str | None = None) -> TTSResult:
        normalized = text.strip()
        if not self.configured:
            raise RuntimeError("DashScope TTS is not configured")
        if not normalized:
            raise ValueError("TTS text must not be empty")
        if len(normalized) > 600:
            raise ValueError("DashScope TTS text exceeds 600 characters")
        selected_voice = self.resolve_voice(voice_type)
        with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
            response = client.post(
                f"{self.base_url}/services/aigc/multimodal-generation/generation",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"model": self.model, "input": {"text": normalized, "voice": selected_voice,
                                                     "language_type": "Chinese",
                                                     **({"instructions": self.instructions}
                                                        if self.instructions and "instruct" in self.model else {})}},
            )
            response.raise_for_status()
            body = response.json()
            audio = (body.get("output") or {}).get("audio") or {}
            url = str(audio.get("url") or "").strip()
            if not url:
                raise RuntimeError(f"DashScope TTS returned no audio: {str(body.get('message', ''))[:200]}")
            download = client.get(url)
            download.raise_for_status()
            payload = download.content
        if not payload:
            raise RuntimeError("DashScope TTS audio download was empty")
        resolved = output.resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        raw = resolved.with_name(f"{resolved.stem}-raw{Path(url.split('?', 1)[0]).suffix or '.wav'}")
        raw.write_bytes(payload)
        completed = subprocess.run(
            [self.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-i", str(raw), "-vn", "-ac", "1",
             "-ar", "24000", "-c:a", "libmp3lame", "-b:a", "128k", "-y", str(resolved)],
            capture_output=True, text=True, timeout=120)
        if completed.returncode != 0 or not resolved.is_file():
            # Keep the raw audio rather than failing: every consumer decodes by content, not suffix.
            resolved.write_bytes(payload)
        raw.unlink(missing_ok=True)
        return TTSResult(path=resolved, duration_seconds=self._measured_duration(resolved),
                         voice_type=selected_voice, character_count=len(normalized))
