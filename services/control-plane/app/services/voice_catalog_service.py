from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class VoicePreset:
    preset_id: str
    voice_type: str
    name: str
    description: str
    use_cases: tuple[str, ...]
    tags: tuple[str, ...]
    source_kind: str
    source_url: str
    preview_text: str


OFFICIAL_SPEAKER_SOURCE = (
    "https://api.volcengine.com/api-docs/view?"
    "action=ListSpeakers&serviceCode=speech_saas_prod&version=2025-05-20"
)
OFFICIAL_RELEASE_SOURCE = "https://www.volcengine.com/docs/6561/162929?lang=en"


class VoiceCatalogService:
    """Curated official presets for short-video narration.

    This is deliberately not a voice-cloning catalog. Every entry maps to a
    documented Volcengine speaker ID and keeps the official source URL visible.
    """

    PRESETS = (
        VoicePreset(
            preset_id="vivi-2",
            voice_type="zh_female_vv_uranus_bigtts",
            name="Vivi 2.0",
            description="活泼、清晰，适合教程、清单和日常知识讲解。",
            use_cases=("教程讲解", "知识分享", "通用口播"),
            tags=("推荐", "TTS 2.0", "字节官方"),
            source_kind="volcengine_official",
            source_url=OFFICIAL_RELEASE_SOURCE,
            preview_text="这个小技巧看起来简单，但真正有用的是下面这一步。",
        ),
        VoicePreset(
            preset_id="sweet-peach",
            voice_type="zh_female_tianmeitaozi_mars_bigtts",
            name="甜美桃子",
            description="亲切甜美的女声，适合生活好物、宠物和轻商品种草。",
            use_cases=("商品介绍", "宠物种草", "生活教程"),
            tags=("热门", "抖音同款", "字节官方"),
            source_kind="volcengine_official",
            source_url=OFFICIAL_SPEAKER_SOURCE,
            preview_text="沙发不再粘毛，其实只差这一步，三秒就能看到变化。",
        ),
        VoicePreset(
            preset_id="smooth-female",
            voice_type="zh_female_santongyongns_saturn_bigtts",
            name="流畅女声",
            description="节奏稳定、信息密度高，适合步骤型教程和功能解说。",
            use_cases=("视频配音", "教程讲解", "产品功能"),
            tags=("视频配音", "清晰", "字节官方"),
            source_kind="volcengine_official",
            source_url=OFFICIAL_RELEASE_SOURCE,
            preview_text="先打开设置，再找到这个开关，最后保存，整个过程只需要三步。",
        ),
        VoicePreset(
            preset_id="dayi",
            voice_type="zh_male_dayi_saturn_bigtts",
            name="大壹",
            description="沉稳有力的男声，适合性能、对比和结论型商品讲解。",
            use_cases=("视频配音", "商品介绍", "对比测评"),
            tags=("视频配音", "沉稳", "字节官方"),
            source_kind="volcengine_official",
            source_url=OFFICIAL_RELEASE_SOURCE,
            preview_text="同样的使用时间，真正拉开差距的，是这个容易被忽略的细节。",
        ),
        VoicePreset(
            preset_id="yunzhou",
            voice_type="zh_male_yunzhou_jupiter_bigtts",
            name="云舟",
            description="清爽、沉稳但不压迫，适合科普、使用说明和长一些的口播。",
            use_cases=("科普口播", "教程讲解", "商品说明"),
            tags=("清爽", "沉稳", "字节官方"),
            source_kind="volcengine_official",
            source_url=OFFICIAL_RELEASE_SOURCE,
            preview_text="别急着看结果，我们先用十秒把原理讲清楚，后面操作就很简单了。",
        ),
    )

    def __init__(self, configured_voice_type: str = "") -> None:
        self.configured_voice_type = configured_voice_type

    def get(self, preset_id: str) -> VoicePreset | None:
        return next((item for item in self.PRESETS if item.preset_id == preset_id), None)

    def list(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for item in self.PRESETS:
            row = asdict(item)
            row["use_cases"] = list(item.use_cases)
            row["tags"] = list(item.tags)
            row["availability"] = (
                "configured_default"
                if self.configured_voice_type and item.voice_type == self.configured_voice_type
                else "unknown_until_preview"
            )
            rows.append(row)
        return rows
