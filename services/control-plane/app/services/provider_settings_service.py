from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json

from sqlmodel import Session, select

from app.config import Settings
from app.models import ProviderCredential
from app.services.secret_store import SecretStore, mask_access_key


@dataclass(frozen=True)
class ProviderField:
    name: str
    setting: str
    label: str
    secret: bool = True
    required: bool = False
    placeholder: str = ""


@dataclass(frozen=True)
class ProviderDefinition:
    provider_id: str
    name: str
    summary: str
    fields: tuple[ProviderField, ...]


PROVIDERS: tuple[ProviderDefinition, ...] = (
    ProviderDefinition(
        "volcano_asr",
        "火山引擎 BigASR",
        "生产任务经允许后使用云端中文转写；失败回退本地 Whisper。",
        (
            ProviderField("api_key", "volcano_asr_api_key", "API Key", placeholder="推荐：语音服务 API Key"),
            ProviderField("app_key", "volcano_asr_app_key", "App Key"),
            ProviderField("access_key", "volcano_asr_access_key", "Access Key"),
            ProviderField("resource_id", "volcano_asr_resource_id", "资源 ID", False, placeholder="volc.bigasr.auc_turbo"),
        ),
    ),
    ProviderDefinition(
        "volcano_tts",
        "火山引擎豆包 TTS",
        "为商品、教程和讲解视频生成官方音色旁白。",
        (
            ProviderField("api_key", "volcano_tts_api_key", "API Key", required=True),
            ProviderField("resource_id", "volcano_tts_resource_id", "资源 ID", False, placeholder="seed-tts-2.0"),
            ProviderField("voice_type", "volcano_tts_voice_type", "默认音色", False, placeholder="官方音色 ID"),
        ),
    ),
    ProviderDefinition(
        "dify",
        "Dify 工作流",
        "教程拆解与爆款结构分析；未配置时继续使用本地策略。",
        (
            ProviderField("base_url", "dify_base_url", "服务地址", False, required=True, placeholder="http://127.0.0.1:5501/v1"),
            ProviderField("tutorial_api_key", "dify_tutorial_api_key", "教程工作流 Key"),
            ProviderField("viral_api_key", "dify_viral_api_key", "爆款工作流 Key"),
        ),
    ),
    ProviderDefinition(
        "pexels",
        "Pexels 公共素材",
        "从官方 API 搜索并登记有来源信息的视频素材。",
        (ProviderField("api_key", "pexels_api_key", "API Key", required=True),),
    ),
    ProviderDefinition(
        "pixabay",
        "Pixabay 公共素材",
        "从官方 API 搜索并登记有许可信息的视频素材。",
        (ProviderField("api_key", "pixabay_api_key", "API Key", required=True),),
    ),
    ProviderDefinition(
        "seedance",
        "Seedance 视频生成",
        "按明确请求生成竖屏视频素材；不会在后台自动触发付费。",
        (
            ProviderField("api_key", "seedance_api_key", "方舟 API Key", required=True),
            ProviderField("model", "seedance_model", "模型推理端点", False, required=True),
            ProviderField("base_url", "seedance_base_url", "服务地址", False, placeholder="https://ark.cn-beijing.volces.com/api/v3"),
        ),
    ),
    ProviderDefinition(
        "douyin",
        "抖音开放平台",
        "搜索需要应用权限；发布还需要账号本人 OAuth。",
        (
            ProviderField("client_key", "douyin_client_key", "Client Key", required=True),
            ProviderField("client_secret", "douyin_client_secret", "Client Secret", required=True),
            ProviderField("device_id", "douyin_device_id", "Device ID", False),
            ProviderField("open_id", "douyin_open_id", "Open ID"),
            ProviderField("access_token", "douyin_access_token", "Access Token"),
        ),
    ),
    ProviderDefinition(
        "dingtalk",
        "钉钉素材入口",
        "从组织内 Stream 机器人接收已授权文件。",
        (
            ProviderField("client_id", "dingtalk_client_id", "Client ID", required=True),
            ProviderField("client_secret", "dingtalk_client_secret", "Client Secret", required=True),
        ),
    ),
)


class ProviderSettingsService:
    def __init__(self, master_secret: str):
        self.secrets = SecretStore(master_secret)
        self._dirty: set[str] = set()

    @staticmethod
    def _definition(provider_id: str) -> ProviderDefinition:
        definition = next((item for item in PROVIDERS if item.provider_id == provider_id), None)
        if definition is None:
            raise KeyError("unknown_provider")
        return definition

    def _values(self, record: ProviderCredential | None) -> dict[str, str]:
        if record is None:
            return {}
        encrypted = json.loads(record.encrypted_values_json or "{}")
        return {name: self.secrets.decrypt(token) for name, token in encrypted.items()}

    @staticmethod
    def _mask(value: str, *, secret: bool) -> str:
        return mask_access_key(value) if secret else value

    def _provider_status(self, session: Session, definition: ProviderDefinition) -> dict[str, object]:
        record = session.get(ProviderCredential, definition.provider_id)
        masked = json.loads(record.masked_values_json or "{}") if record else {}
        configured_names = set(masked)
        if definition.provider_id == "volcano_asr":
            complete = "api_key" in configured_names or {"app_key", "access_key"}.issubset(configured_names)
        elif definition.provider_id == "dify":
            complete = "base_url" in configured_names and bool(
                {"tutorial_api_key", "viral_api_key"} & configured_names
            )
        else:
            required = {field.name for field in definition.fields if field.required}
            complete = bool(configured_names) and required.issubset(configured_names)
        return {
            "id": definition.provider_id,
            "name": definition.name,
            "summary": definition.summary,
            "configured": bool(configured_names),
            "complete": complete,
            "restart_required": definition.provider_id in self._dirty,
            "fields": [
                {
                    "name": field.name,
                    "label": field.label,
                    "secret": field.secret,
                    "required": field.required,
                    "placeholder": field.placeholder,
                    "configured": field.name in configured_names,
                    "masked_value": masked.get(field.name, ""),
                }
                for field in definition.fields
            ],
        }

    def status(self, session: Session) -> dict[str, object]:
        return {
            "providers": [self._provider_status(session, definition) for definition in PROVIDERS],
            "restart_required": bool(self._dirty),
            "security": "凭据在本机加密保存，API 只返回掩码；保存后重启本地服务生效。",
        }

    def save(
        self,
        session: Session,
        provider_id: str,
        *,
        values: dict[str, str],
        clear_fields: list[str] | None = None,
    ) -> dict[str, object]:
        definition = self._definition(provider_id)
        field_map = {field.name: field for field in definition.fields}
        unknown = (set(values) | set(clear_fields or [])) - set(field_map)
        if unknown:
            raise ValueError("unknown_provider_field")
        record = session.get(ProviderCredential, provider_id)
        merged = self._values(record)
        for name in clear_fields or []:
            merged.pop(name, None)
        for name, raw_value in values.items():
            normalized = str(raw_value).strip()
            if len(normalized) > 2048:
                raise ValueError("provider_value_too_long")
            if normalized:
                merged[name] = normalized
        if merged:
            record = record or ProviderCredential(provider_id=provider_id)
            record.encrypted_values_json = json.dumps(
                {name: self.secrets.encrypt(value) for name, value in merged.items()},
                ensure_ascii=False,
            )
            record.masked_values_json = json.dumps(
                {
                    name: self._mask(value, secret=field_map[name].secret)
                    for name, value in merged.items()
                },
                ensure_ascii=False,
            )
            record.updated_at = datetime.now(UTC)
            session.add(record)
        elif record is not None:
            session.delete(record)
        session.commit()
        self._dirty.add(provider_id)
        return self._provider_status(session, definition)

    def delete(self, session: Session, provider_id: str) -> dict[str, object]:
        definition = self._definition(provider_id)
        record = session.get(ProviderCredential, provider_id)
        if record is not None:
            session.delete(record)
            session.commit()
        self._dirty.add(provider_id)
        return self._provider_status(session, definition)

    def apply(self, session: Session, settings: Settings) -> None:
        records = list(session.exec(select(ProviderCredential)).all())
        definitions = {item.provider_id: item for item in PROVIDERS}
        for record in records:
            definition = definitions.get(record.provider_id)
            if definition is None:
                continue
            field_map = {field.name: field for field in definition.fields}
            for name, value in self._values(record).items():
                field = field_map.get(name)
                if field is None:
                    continue
                current = getattr(settings, field.setting)
                if isinstance(current, int):
                    try:
                        value = int(value)
                    except ValueError:
                        continue
                setattr(settings, field.setting, value)
        self._dirty.clear()
