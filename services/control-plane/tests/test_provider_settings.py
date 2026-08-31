from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.config import Settings
from app.main import create_app
from app.models import ProviderCredential


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'providers.db').as_posix()}",
        automation_enabled=False,
    )


def test_provider_settings_save_masks_and_encrypts_secret(tmp_path: Path):
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        initial = client.get("/api/provider-settings")
        assert initial.status_code == 200
        assert {item["id"] for item in initial.json()["providers"]} >= {
            "volcano_asr",
            "volcano_tts",
            "dify",
            "pexels",
            "pixabay",
            "seedance",
            "douyin",
            "dingtalk",
        }

        response = client.put(
            "/api/provider-settings/pexels",
            json={"values": {"api_key": "pexels-sensitive-example"}},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["configured"] is True
        assert payload["restart_required"] is True
        field = next(item for item in payload["fields"] if item["name"] == "api_key")
        assert field["configured"] is True
        assert field["masked_value"].startswith("pexe")
        assert "pexels-sensitive-example" not in response.text

        with Session(client.app.state.database.engine) as session:
            stored = session.get(ProviderCredential, "pexels")
            assert stored is not None
            assert "pexels-sensitive-example" not in stored.encrypted_values_json
            assert "pexels-sensitive-example" not in stored.masked_values_json


def test_saved_provider_settings_apply_on_next_start(tmp_path: Path):
    first_settings = settings_for(tmp_path)
    with TestClient(create_app(first_settings)) as client:
        saved = client.put(
            "/api/provider-settings/dify",
            json={
                "values": {
                    "base_url": "http://127.0.0.1:5501/v1",
                    "tutorial_api_key": "tutorial-secret-example",
                    "viral_api_key": "viral-secret-example",
                }
            },
        )
        assert saved.status_code == 200

    restarted_settings = settings_for(tmp_path)
    with TestClient(create_app(restarted_settings)) as restarted:
        assert restarted.app.state.settings.dify_base_url == "http://127.0.0.1:5501/v1"
        assert restarted.app.state.settings.dify_tutorial_api_key == "tutorial-secret-example"
        status = restarted.get("/api/provider-settings").json()
        dify = next(item for item in status["providers"] if item["id"] == "dify")
        assert dify["configured"] is True
        assert dify["restart_required"] is False
        assert "tutorial-secret-example" not in restarted.get("/api/provider-settings").text


def test_provider_settings_reject_unknown_fields_and_support_delete(tmp_path: Path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        rejected = client.put(
            "/api/provider-settings/pexels",
            json={"values": {"not_a_real_field": "value"}},
        )
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] == "unknown_provider_field"

        client.put(
            "/api/provider-settings/pexels",
            json={"values": {"api_key": "pexels-sensitive-example"}},
        )
        deleted = client.delete("/api/provider-settings/pexels")
        assert deleted.status_code == 200
        assert deleted.json()["configured"] is False
        assert deleted.json()["restart_required"] is True


def test_provider_settings_page_is_linked_from_setup_and_capability_guide(tmp_path: Path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        page = client.get("/settings/providers")
        assert page.status_code == 200
        assert 'id="provider-settings-list"' in page.text
        assert "可选增强配置" in page.text
        assert "/static/provider-settings.js" in page.text

        setup = client.get("/setup")
        guide = client.get("/docs/capabilities-and-configuration")
        assert 'href="/settings/providers"' in setup.text
        assert 'href="/settings/providers"' in guide.text
