from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


LOCAL_FEATURES = ["本地上传", "智能分析", "自动剪辑", "字幕与预览", "剪映草稿"]


class SetupService:
    """Build non-secret first-run guidance from existing runtime facts."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.preference_path = self.data_dir / "setup-preferences.json"

    def preferences(self) -> dict[str, bool]:
        try:
            payload = json.loads(self.preference_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {"local_mode_confirmed": False}
        return {"local_mode_confirmed": payload.get("local_mode_confirmed") is True}

    def update_preferences(self, *, local_mode_confirmed: bool) -> dict[str, bool]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = {"local_mode_confirmed": bool(local_mode_confirmed)}
        temporary = self.preference_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self.preference_path)
        return payload

    def status(
        self,
        *,
        runtime: dict[str, Any],
        integrations: dict[str, dict[str, Any]],
        materials: dict[str, Any],
    ) -> dict[str, Any]:
        preferences = self.preferences()
        tools = runtime.get("tools") or {}
        runtime_paths = runtime.get("runtime") or {}
        local_ready = bool(
            runtime_paths.get("data_dir")
            and runtime_paths.get("inbox_dir")
            and tools.get("ffmpeg", True)
            and tools.get("ffprobe", True)
        )
        providers = [
            self._volcengine_card(integrations),
            self._materials_card(integrations, materials),
            self._douyin_card(integrations),
            self._dingtalk_card(integrations),
        ]
        configured_optional = sum(card["status"] == "configured" for card in providers)
        return {
            "first_run": not preferences["local_mode_confirmed"],
            "local_mode": {
                "ready": local_ready,
                "confirmed": preferences["local_mode_confirmed"],
                "available_features": LOCAL_FEATURES,
            },
            "runtime": runtime,
            "providers": providers,
            "progress": {
                "local_ready": local_ready,
                "configured_optional": configured_optional,
                "optional_total": len(providers),
            },
        }

    @staticmethod
    def _status(item: dict[str, Any] | None) -> str:
        value = (item or {}).get("status", "not_configured")
        if value in {"configured", "partially_configured", "not_configured", "oauth_required", "permission_required", "unreachable"}:
            return value
        return "not_configured"

    def _volcengine_card(self, integrations: dict[str, dict[str, Any]]) -> dict[str, Any]:
        asr_status = self._status(integrations.get("asr"))
        tts_status = self._status(integrations.get("tts"))
        configured = asr_status == "configured" and tts_status == "configured"
        partial = asr_status == "configured" or tts_status == "configured"
        return {
            "id": "volcengine",
            "name": "火山引擎增强",
            "summary": "使用云端高质量转写、热门讲解音色和方舟模型。",
            "required": False,
            "status": "configured" if configured else "partially_configured" if partial else "not_configured",
            "detail": "未连接时自动使用本地 Whisper 和本地剪辑。",
            "fallback": "本地 Whisper 与本地剪辑",
            "official_url": "https://console.volcengine.com/ark",
            "guide_url": "/docs/user-required-actions#火山引擎",
            "fields": ["方舟访问凭证（按需）", "语音服务凭证（按需）", "只读用量凭证（按需）"],
            "next_action": "按需要分别开通模型、语音或只读用量查询。",
        }

    def _materials_card(
        self,
        integrations: dict[str, dict[str, Any]],
        materials: dict[str, Any],
    ) -> dict[str, Any]:
        total = int(materials.get("total") or 0)
        pexels_status = self._status(materials.get("pexels"))
        pixabay_status = self._status(materials.get("pixabay"))
        external_ready = "configured" in {pexels_status, pixabay_status}
        local_ready = total > 0 or self._status(integrations.get("materials")) == "configured"
        if total:
            detail = f"本地已有 {total} 条授权素材；" + ("公共素材接口已连接。" if external_ready else "公共素材接口尚未连接。")
        else:
            detail = "可以直接上传自有素材；公共素材接口为可选增强。"
        return {
            "id": "materials",
            "name": "公共素材库",
            "summary": "从 Pexels 或 Pixabay 搜索有来源记录的公开视频素材。",
            "required": False,
            "status": "configured" if external_ready or local_ready else "not_configured",
            "detail": detail,
            "fallback": "用户上传与本地授权素材",
            "official_url": "https://www.pexels.com/api/",
            "secondary_official_url": "https://pixabay.com/api/docs/",
            "guide_url": "/docs/user-required-actions#可选素材与生成服务",
            "fields": ["Pexels 访问凭证（可选）", "Pixabay 访问凭证（可选）"],
            "next_action": "没有访问凭证也可以直接上传自己的视频。",
        }

    def _douyin_card(self, integrations: dict[str, dict[str, Any]]) -> dict[str, Any]:
        search = self._status(integrations.get("douyin"))
        delivery = self._status(integrations.get("douyin_delivery"))
        if search == "configured" and delivery == "configured":
            status = "configured"
        elif search == "configured" or delivery == "configured":
            status = "partially_configured"
        elif delivery in {"oauth_required", "permission_required"}:
            status = delivery
        else:
            status = "not_configured"
        return {
            "id": "douyin",
            "name": "抖音开放平台",
            "summary": "使用官方热点搜索，并在应用审批和用户授权后发布视频。",
            "required": False,
            "status": status,
            "detail": "需要应用审批和发布账号本人授权；剪映本地草稿不需要此连接。",
            "fallback": "公开热点证据与剪映本地草稿",
            "official_url": "https://open.douyin.com/platform/",
            "guide_url": "/docs/user-required-actions#抖音开放平台应用与-oauth",
            "fields": ["应用标识", "应用密钥", "发布账号授权"],
            "next_action": "先创建应用并申请搜索或发布权限，再由账号本人授权。",
        }

    def _dingtalk_card(self, integrations: dict[str, dict[str, Any]]) -> dict[str, Any]:
        status = self._status(integrations.get("dingtalk"))
        return {
            "id": "dingtalk",
            "name": "钉钉素材入口",
            "summary": "从组织内的钉钉机器人接收已授权文件。",
            "required": False,
            "status": status,
            "detail": "未连接时直接在工作台上传文件。",
            "fallback": "工作台本地上传",
            "official_url": "https://open-dev.dingtalk.com/",
            "guide_url": "/docs/user-required-actions#钉钉",
            "fields": ["机器人应用标识", "机器人应用密钥"],
            "next_action": "创建 Stream 模式机器人并完成组织授权。",
        }
