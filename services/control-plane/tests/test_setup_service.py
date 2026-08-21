from __future__ import annotations

import json
from pathlib import Path

from app.services.setup_service import SetupService


def ready_runtime() -> dict:
    return {
        "platform": "Darwin",
        "architecture": "arm64",
        "runtime": {
            "data_dir": "/Users/demo/Library/Application Support/VideoWorkbench",
            "inbox_dir": "/Users/demo/Movies/VideoWorkbench Inbox",
        },
        "tools": {"ffmpeg": True, "ffprobe": True},
        "jianying": {
            "installed": True,
            "app_path": "/Applications/JianyingPro.app",
            "draft_root": None,
            "needs_folder_picker": True,
        },
    }


def test_fresh_setup_keeps_external_providers_optional(tmp_path: Path):
    service = SetupService(tmp_path)

    result = service.status(runtime=ready_runtime(), integrations={}, materials={})

    assert result["local_mode"] == {
        "ready": True,
        "confirmed": False,
        "available_features": ["本地上传", "智能分析", "自动剪辑", "字幕与预览", "剪映草稿"],
    }
    assert [card["id"] for card in result["providers"]] == [
        "volcengine",
        "materials",
        "douyin",
        "dingtalk",
    ]
    assert all(card["required"] is False for card in result["providers"])
    assert all(card["official_url"].startswith("https://") for card in result["providers"])
    assert result["progress"]["local_ready"] is True
    assert result["progress"]["configured_optional"] == 0


def test_preferences_round_trip_without_secrets(tmp_path: Path):
    service = SetupService(tmp_path)

    saved = service.update_preferences(local_mode_confirmed=True)

    assert saved == {"local_mode_confirmed": True}
    assert service.preferences() == saved
    serialized = (tmp_path / "setup-preferences.json").read_text(encoding="utf-8")
    assert json.loads(serialized) == saved
    assert "secret" not in serialized.lower()
    assert "token" not in serialized.lower()
    assert "api_key" not in serialized.lower()


def test_setup_status_maps_existing_integrations_without_exposing_values(tmp_path: Path):
    service = SetupService(tmp_path)

    result = service.status(
        runtime=ready_runtime(),
        integrations={
            "asr": {"status": "configured", "provider": "volcano_bigasr"},
            "tts": {"status": "configured", "provider": "doubao_tts_2_0"},
            "materials": {"status": "configured", "provider": "local_catalog"},
            "douyin": {"status": "not_configured", "reason": "missing_client_key_and_client_secret"},
            "douyin_delivery": {"status": "oauth_required", "reason": "missing_open_id_or_access_token"},
            "dingtalk": {"status": "not_configured", "reason": "missing_client_id_and_client_secret"},
        },
        materials={
            "total": 3,
            "pexels": {"status": "not_configured", "reason": "missing_api_key"},
            "pixabay": {"status": "not_configured", "reason": "missing_api_key"},
        },
    )

    cards = {card["id"]: card for card in result["providers"]}
    assert cards["volcengine"]["status"] == "configured"
    assert cards["materials"]["status"] == "configured"
    assert cards["materials"]["detail"] == "本地已有 3 条授权素材；公共素材接口尚未连接。"
    assert cards["douyin"]["status"] == "oauth_required"
    assert cards["dingtalk"]["status"] == "not_configured"
    response_text = json.dumps(result, ensure_ascii=False).lower()
    assert "client_secret" not in response_text
    assert "access_token" not in response_text
    assert "api_key" not in response_text
