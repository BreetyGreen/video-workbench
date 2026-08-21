from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

import httpx
import pytest

from app.adapters.volcano_tts import VolcanoTTSClient


def test_volcano_tts_uses_v3_api_key_and_writes_all_audio_chunks(tmp_path: Path):
    requests: list[httpx.Request] = []
    first = base64.b64encode(b"first-audio-").decode("ascii")
    second = base64.b64encode(b"second-audio").decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        content = "".join(
            [
                json.dumps({"code": 0, "data": first}),
                json.dumps(
                    {
                        "code": 0,
                        "data": second,
                        "addition": {"duration": "1250"},
                    }
                ),
                json.dumps({"code": 20000000, "message": "OK"}),
            ]
        )
        return httpx.Response(200, text=content)

    client = VolcanoTTSClient(
        api_key="speech-key",
        voice_type="zh_female_vv_uranus_bigtts",
        transport=httpx.MockTransport(handler),
    )
    output = tmp_path / "voiceover.mp3"

    result = client.synthesize("小狗今天第一次学会握手。", output)

    assert result.path == output.resolve()
    assert result.duration_seconds == pytest.approx(1.25)
    assert result.voice_type == "zh_female_vv_uranus_bigtts"
    assert result.character_count == len("小狗今天第一次学会握手。")
    assert output.read_bytes() == b"first-audio-second-audio"
    request = requests[0]
    assert request.headers["x-api-key"] == "speech-key"
    assert request.headers["x-api-resource-id"] == "seed-tts-2.0"
    assert "speech-key" not in request.content.decode("utf-8")
    payload = json.loads(request.content)
    assert payload["req_params"]["speaker"] == "zh_female_vv_uranus_bigtts"
    assert payload["req_params"]["audio_params"] == {"format": "mp3", "sample_rate": 24000}


def test_volcano_tts_rejects_unconfigured_client(tmp_path: Path):
    client = VolcanoTTSClient(api_key="")

    with pytest.raises(RuntimeError, match="not configured"):
        client.synthesize("测试", tmp_path / "voice.mp3")


def test_volcano_tts_allows_a_per_request_voice_override(tmp_path: Path):
    requests: list[httpx.Request] = []
    encoded = base64.b64encode(b"voice").decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=json.dumps({"code": 0, "data": encoded, "addition": {"duration": "500"}}))

    client = VolcanoTTSClient(
        api_key="speech-key",
        voice_type="zh_female_vv_uranus_bigtts",
        transport=httpx.MockTransport(handler),
    )
    result = client.synthesize(
        "商品讲解试听",
        tmp_path / "override.mp3",
        voice_type="zh_male_dayi_saturn_bigtts",
    )

    payload = json.loads(requests[0].content)
    assert payload["req_params"]["speaker"] == "zh_male_dayi_saturn_bigtts"
    assert result.voice_type == "zh_male_dayi_saturn_bigtts"
    assert client.voice_type == "zh_female_vv_uranus_bigtts"


def test_volcano_tts_surfaces_api_error_without_writing_output(tmp_path: Path):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=json.dumps({"code": 55000000, "message": "resource mismatch"}))

    output = tmp_path / "voice.mp3"
    client = VolcanoTTSClient(
        api_key="speech-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match="resource mismatch"):
        client.synthesize("测试", output)

    assert not output.exists()


def test_volcano_tts_uses_measured_audio_duration_over_unreliable_metadata(
    tmp_path: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
):
    generated = tmp_path / "generated.mp3"
    subprocess.run(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=24000:d=1",
            "-y",
            str(generated),
        ],
        check=True,
    )
    encoded = base64.b64encode(generated.read_bytes()).decode("ascii")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="".join(
                [
                    json.dumps({"code": 0, "data": encoded, "addition": {"duration": "200"}}),
                    json.dumps({"code": 20000000, "message": "OK"}),
                ]
            ),
        )

    result = VolcanoTTSClient(
        api_key="speech-key",
        ffprobe_bin=ffprobe_bin,
        transport=httpx.MockTransport(handler),
    ).synthesize("测试真实音频时长。", tmp_path / "voiceover.mp3")

    assert result.duration_seconds == pytest.approx(1.0, abs=0.05)
