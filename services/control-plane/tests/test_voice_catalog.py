from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.adapters.volcano_tts import TTSResult
from app.config import Settings
from app.main import create_app


class FakePreviewTTS:
    configured = True
    voice_type = "zh_female_vv_uranus_bigtts"

    def synthesize(self, text: str, output: Path, *, voice_type: str | None = None) -> TTSResult:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"preview-audio")
        return TTSResult(
            path=output.resolve(),
            duration_seconds=1.5,
            voice_type=voice_type or self.voice_type,
            character_count=len(text.strip()),
        )


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'voices.db').as_posix()}",
        automation_enabled=False,
        volcano_tts_api_key="",
        volcano_asr_api_key="",
    )


def test_voice_center_lists_officially_sourced_explainer_presets(tmp_path: Path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.get("/api/voices")
        page = client.get("/voices")

    assert response.status_code == 200
    presets = response.json()["voices"]
    assert len(presets) >= 5
    sweet_peach = next(item for item in presets if item["preset_id"] == "sweet-peach")
    assert sweet_peach["name"] == "甜美桃子"
    assert "抖音同款" in sweet_peach["tags"]
    assert sweet_peach["source_kind"] == "volcengine_official"
    assert sweet_peach["source_url"].startswith("https://")
    assert sweet_peach["availability"] == "unknown_until_preview"
    assert page.status_code == 200
    assert "官方授权音色" in page.text
    assert 'id="voice-grid"' in page.text
    assert "/static/voices.js" in page.text


def test_voice_preview_requires_configured_tts(tmp_path: Path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.post(
            "/api/voices/vivi-2/preview",
            json={"text": "这是一段教程试听。"},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "tts_not_configured"


def test_voice_preview_generates_audio_and_records_local_usage(tmp_path: Path):
    with TestClient(create_app(settings_for(tmp_path), tts_client=FakePreviewTTS())) as client:
        response = client.post(
            "/api/voices/sweet-peach/preview",
            json={"text": "沙发不再粘毛，其实只差这一步。"},
        )
        assert response.status_code == 200
        payload = response.json()
        audio = client.get(payload["audio_url"])
        usage = client.get("/api/cloud-usage/summary").json()["local"]

    assert payload["voice_type"] == "zh_female_tianmeitaozi_mars_bigtts"
    assert payload["character_count"] == len("沙发不再粘毛，其实只差这一步。")
    assert audio.status_code == 200
    assert audio.content == b"preview-audio"
    assert usage["tts"]["used"] == payload["character_count"]


def test_unknown_voice_preset_is_rejected(tmp_path: Path):
    with TestClient(create_app(settings_for(tmp_path), tts_client=FakePreviewTTS())) as client:
        response = client.post("/api/voices/not-a-real-voice/preview", json={"text": "试听"})

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "voice_not_found"
