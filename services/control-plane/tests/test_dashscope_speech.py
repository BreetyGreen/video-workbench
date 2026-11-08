from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from app.adapters.dashscope_speech import DashScopeParaformerTranscriber, DashScopeTTSClient

BASE = "https://ws-test.cn-beijing.maas.aliyuncs.com/api/v1"


def transcript_payload() -> dict:
    return {"transcripts": [{"content_duration_in_milliseconds": 4200, "sentences": [
        {"begin_time": 500, "end_time": 2100, "text": "先把气口剪掉。",
         "words": [{"begin_time": 500, "end_time": 900, "text": "先把", "punctuation": ""},
                   {"begin_time": 900, "end_time": 1600, "text": "气口", "punctuation": ""},
                   {"begin_time": 1600, "end_time": 2100, "text": "剪掉", "punctuation": "。"}]},
        {"begin_time": 2500, "end_time": 4100, "text": "然后配镜头。", "words": []},
    ]}]}


def test_paraformer_uploads_submits_polls_and_converts_words(tmp_path: Path, ffmpeg_fixture: Path, ffmpeg_bin: str):
    seen: list[tuple[str, str]] = []
    polls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/uploads"):
            assert request.headers["authorization"] == "Bearer sk-test"
            assert request.url.params["model"] == "paraformer-v2"
            return httpx.Response(200, json={"data": {"policy": "p", "signature": "s", "upload_dir": "dashscope-instant/ws/2026",
                                                     "upload_host": "https://oss.test", "oss_access_key_id": "ak",
                                                     "x_oss_object_acl": "private", "x_oss_forbid_overwrite": "true"}})
        if request.url.host == "oss.test":
            body = request.content
            assert b'name="OSSAccessKeyId"' in body and b'name="file"' in body
            assert body.rfind(b'name="file"') > body.rfind(b'name="policy"')  # file is the last part
            return httpx.Response(200)
        if request.url.path.endswith("/services/audio/asr/transcription"):
            assert request.headers["x-dashscope-async"] == "enable"
            assert request.headers["x-dashscope-ossresourceresolve"] == "enable"
            payload = json.loads(request.content)
            assert payload["model"] == "paraformer-v2"
            assert payload["input"]["file_urls"][0].startswith("oss://dashscope-instant/ws/2026/")
            return httpx.Response(200, json={"output": {"task_id": "task-1", "task_status": "PENDING"}})
        if request.url.path.endswith("/tasks/task-1"):
            polls["count"] += 1
            if polls["count"] == 1:
                return httpx.Response(200, json={"output": {"task_status": "RUNNING"}})
            return httpx.Response(200, json={"output": {"task_status": "SUCCEEDED", "results": [
                {"subtask_status": "SUCCEEDED", "transcription_url": "https://result.test/t.json"}]}})
        if request.url.host == "result.test":
            return httpx.Response(200, json=transcript_payload())
        raise AssertionError(f"unexpected request {request.url}")

    transcriber = DashScopeParaformerTranscriber(api_key="sk-test", base_url=BASE, poll_seconds=0, ffmpeg_bin=ffmpeg_bin,
                                                 transport=httpx.MockTransport(handler))
    result = transcriber.transcribe(ffmpeg_fixture)

    assert result.provider == "dashscope_paraformer" and result.model == "paraformer-v2"
    assert result.duration_seconds == pytest.approx(4.2)
    assert [s.text for s in result.segments] == ["先把气口剪掉。", "然后配镜头。"]
    assert (result.segments[0].start_seconds, result.segments[0].end_seconds) == (0.5, 2.1)
    assert [(w.text, w.start_seconds, w.end_seconds) for w in result.segments[0].words] == [
        ("先把", 0.5, 0.9), ("气口", 0.9, 1.6), ("剪掉", 1.6, 2.1)]
    assert [path for _, path in seen][:3] == ["/api/v1/uploads", "/", "/api/v1/services/audio/asr/transcription"]
    assert polls["count"] == 2


def test_paraformer_failed_task_raises_and_unconfigured_never_calls(tmp_path: Path, ffmpeg_fixture: Path, ffmpeg_bin: str):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/uploads"):
            return httpx.Response(200, json={"data": {"policy": "p", "signature": "s", "upload_dir": "d",
                                                     "upload_host": "https://oss.test", "oss_access_key_id": "ak"}})
        if request.url.host == "oss.test":
            return httpx.Response(200)
        if request.url.path.endswith("/transcription"):
            return httpx.Response(200, json={"output": {"task_id": "task-2"}})
        return httpx.Response(200, json={"output": {"task_status": "FAILED", "message": "bad audio"}})

    transcriber = DashScopeParaformerTranscriber(api_key="sk-test", base_url=BASE, poll_seconds=0, ffmpeg_bin=ffmpeg_bin,
                                                 transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="FAILED"):
        transcriber.transcribe(ffmpeg_fixture)

    calls = []
    unconfigured = DashScopeParaformerTranscriber(api_key="", base_url=BASE,
                                                  transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200)))
    assert unconfigured.configured is False
    with pytest.raises(RuntimeError):
        unconfigured.transcribe(ffmpeg_fixture)
    assert calls == []


def test_tts_downloads_audio_and_maps_foreign_voice_to_default(tmp_path: Path, ffmpeg_bin: str, ffprobe_bin: str):
    wav = tmp_path / "sample.wav"
    subprocess.run([ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=24000:d=1.5", str(wav)], check=True, capture_output=True, text=True)
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/multimodal-generation/generation"):
            body = json.loads(request.content)
            requests.append(body)
            return httpx.Response(200, json={"output": {"audio": {"url": "https://audio.test/out.wav?x=1", "id": "a1"}},
                                             "usage": {"characters": len(body["input"]["text"])}})
        if request.url.host == "audio.test":
            return httpx.Response(200, content=wav.read_bytes())
        raise AssertionError(request.url)

    client = DashScopeTTSClient(api_key="sk-test", base_url=BASE, voice_type="Cherry", ffmpeg_bin=ffmpeg_bin,
                                ffprobe_bin=ffprobe_bin, transport=httpx.MockTransport(handler))
    output = tmp_path / "voiceover.mp3"
    result = client.synthesize("果知纯绿豆沙来了。", output, voice_type="zh_female_vv_uranus_bigtts")

    assert requests[0]["model"] == "qwen3-tts-flash"
    assert requests[0]["input"] == {"text": "果知纯绿豆沙来了。", "voice": "Cherry", "language_type": "Chinese"}
    assert result.path == output.resolve() and output.stat().st_size > 0
    assert result.voice_type == "Cherry" and result.character_count == 9
    assert result.duration_seconds == pytest.approx(1.5, abs=0.15)
    assert not list(tmp_path.glob("voiceover-raw*"))
    assert client.resolve_voice("Serena") == "Serena"


def test_tts_rejects_empty_and_overlong_text(tmp_path: Path):
    client = DashScopeTTSClient(api_key="sk-test", base_url=BASE, transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(ValueError):
        client.synthesize("   ", tmp_path / "x.mp3")
    with pytest.raises(ValueError):
        client.synthesize("字" * 601, tmp_path / "x.mp3")
    assert DashScopeTTSClient(api_key="", base_url=BASE).configured is False


def test_paraformer_treats_no_valid_fragment_as_empty_transcript(ffmpeg_fixture: Path, ffmpeg_bin: str):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/uploads"):
            return httpx.Response(200, json={"data": {"policy": "p", "signature": "s", "upload_dir": "d",
                                                     "upload_host": "https://oss.test", "oss_access_key_id": "ak"}})
        if request.url.host == "oss.test":
            return httpx.Response(200)
        if request.url.path.endswith("/transcription"):
            return httpx.Response(200, json={"output": {"task_id": "task-silent"}})
        return httpx.Response(200, json={"output": {"task_status": "FAILED", "code": "SUCCESS_WITH_NO_VALID_FRAGMENT",
                                                    "message": "no valid speech fragment"}})

    transcriber = DashScopeParaformerTranscriber(api_key="sk-test", base_url=BASE, poll_seconds=0, ffmpeg_bin=ffmpeg_bin,
                                                 transport=httpx.MockTransport(handler))
    result = transcriber.transcribe(ffmpeg_fixture)
    assert result.provider == "dashscope_paraformer" and result.segments == []


def test_designed_voice_ids_are_accepted_as_default_or_explicit():
    client = DashScopeTTSClient(api_key="sk-test", base_url=BASE, model="qwen3-tts-vd-2026-01-26",
                                voice_type="qwen-tts-vd-saleshost-voice-20260911-abcd")
    assert client.resolve_voice("zh_female_vv_uranus_bigtts") == "qwen-tts-vd-saleshost-voice-20260911-abcd"
    assert client.resolve_voice("qwen-tts-vc-clone-1") == "qwen-tts-vc-clone-1"
    assert DashScopeTTSClient(api_key="k", base_url=BASE, voice_type="nonsense").resolve_voice(None) == "Cherry"


def test_cosyvoice_client_uses_sdk_factory_and_maps_voices(tmp_path: Path, ffmpeg_bin: str, ffprobe_bin: str):
    from app.adapters.dashscope_speech import DashScopeCosyVoiceClient

    wav = tmp_path / "s.wav"
    subprocess.run([ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=22050:d=1.2", str(wav)], check=True, capture_output=True, text=True)
    calls = []

    class FakeSynth:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def call(self, text):
            calls[-1]["text"] = text
            return wav.read_bytes()

    client = DashScopeCosyVoiceClient(api_key="sk-test", voice_type="longxiaochun_v2", speech_rate=1.1,
                                      ffprobe_bin=ffprobe_bin, synthesizer_factory=FakeSynth)
    result = client.synthesize("冰爽一口透心凉。", tmp_path / "vo.mp3", voice_type="zh_female_vv_uranus_bigtts")
    assert calls[0]["model"] == "cosyvoice-v2" and calls[0]["voice"] == "longxiaochun_v2" and calls[0]["speech_rate"] == 1.1
    assert result.voice_type == "longxiaochun_v2" and result.character_count == 8
    assert result.duration_seconds == pytest.approx(1.2, abs=0.15) and (tmp_path / "vo.mp3").stat().st_size > 0
    assert client.resolve_voice("longwan_v2") == "longwan_v2"
    assert DashScopeCosyVoiceClient(api_key="").configured is False


def test_build_tts_client_picks_cosyvoice_engine():
    from app.config import Settings
    from app.services.pipeline_service import build_tts_client
    from app.adapters.dashscope_speech import DashScopeCosyVoiceClient, DashScopeTTSClient

    base = dict(dashscope_api_key="k", dashscope_base_url=BASE, speech_provider="dashscope")
    assert isinstance(build_tts_client(Settings(**base, dashscope_tts_engine="cosyvoice")), DashScopeCosyVoiceClient)
    assert isinstance(build_tts_client(Settings(**base, dashscope_tts_engine="qwen")), DashScopeTTSClient)
