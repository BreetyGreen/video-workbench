from __future__ import annotations

import base64
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx


@dataclass(frozen=True)
class TTSResult:
    path: Path
    duration_seconds: float
    voice_type: str
    character_count: int = 0


class VolcanoTTSClient:
    def __init__(
        self,
        *,
        api_key: str,
        resource_id: str = "seed-tts-2.0",
        endpoint: str = "https://openspeech.bytedance.com/api/v3/tts/unidirectional",
        voice_type: str = "zh_female_vv_uranus_bigtts",
        timeout_seconds: float = 90.0,
        ffprobe_bin: str = "ffprobe",
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key.strip()
        self.resource_id = resource_id.strip() or "seed-tts-2.0"
        self.endpoint = endpoint
        self.voice_type = voice_type.strip() or "zh_female_vv_uranus_bigtts"
        self.timeout_seconds = timeout_seconds
        self.ffprobe_bin = ffprobe_bin
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @staticmethod
    def _messages(content: str) -> list[dict[str, object]]:
        decoder = json.JSONDecoder()
        cursor = 0
        messages: list[dict[str, object]] = []
        while cursor < len(content):
            while cursor < len(content) and content[cursor].isspace():
                cursor += 1
            if cursor >= len(content):
                break
            message, cursor = decoder.raw_decode(content, cursor)
            if isinstance(message, dict):
                messages.append(message)
        return messages

    def _measured_duration(self, path: Path) -> float:
        try:
            completed = subprocess.run(
                [
                    self.ffprobe_bin,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if completed.returncode != 0:
                return 0
            payload = json.loads(completed.stdout)
            return max(0, float(payload.get("format", {}).get("duration", 0) or 0))
        except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired):
            return 0

    def synthesize(self, text: str, output: Path, *, voice_type: str | None = None) -> TTSResult:
        normalized = text.strip()
        if not self.configured:
            raise RuntimeError("Volcano TTS is not configured")
        if not normalized:
            raise ValueError("TTS text must not be empty")

        headers = {
            "X-Api-Key": self.api_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": str(uuid4()),
            "Content-Type": "application/json",
        }
        selected_voice_type = (voice_type or "").strip() or self.voice_type
        payload = {
            "user": {"uid": "automated-video-workbench"},
            "req_params": {
                "text": normalized,
                "speaker": selected_voice_type,
                "audio_params": {"format": "mp3", "sample_rate": 24000},
            },
        }
        with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
            response = client.post(self.endpoint, headers=headers, json=payload)
        response.raise_for_status()

        chunks: list[bytes] = []
        duration_seconds = 0.0
        for message in self._messages(response.text):
            code = int(message.get("code", -1) or 0)
            if code not in {0, 20000000}:
                raise RuntimeError(f"Volcano TTS failed ({code}): {message.get('message', 'unknown error')}")
            data = message.get("data")
            if isinstance(data, str) and data:
                chunks.append(base64.b64decode(data))
            addition = message.get("addition")
            if isinstance(addition, dict) and addition.get("duration"):
                duration_seconds = max(duration_seconds, float(addition["duration"]) / 1000)
        if not chunks:
            raise RuntimeError("Volcano TTS returned no audio")

        resolved = output.resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_bytes(b"".join(chunks))
        duration_seconds = self._measured_duration(resolved) or duration_seconds
        return TTSResult(
            path=resolved,
            duration_seconds=duration_seconds,
            voice_type=selected_voice_type,
            character_count=len(normalized),
        )
