from __future__ import annotations

from pathlib import Path

from app.adapters.volcano_tts import TTSResult
from app.schemas.editing import MediaAnalysis, TranscriptResult, TranscriptSegment
from app.services.audio_routing_service import AudioRoutingService


def analysis(
    *,
    duration: float = 10,
    has_audio: bool = True,
    segments: list[tuple[str, float, float]] | None = None,
) -> MediaAnalysis:
    return MediaAnalysis(
        material_id="material-1",
        source_path="C:/media/pet.mp4",
        duration_seconds=duration,
        width=1080,
        height=1920,
        has_audio=has_audio,
        transcript=TranscriptResult(
            duration_seconds=duration,
            segments=[
                TranscriptSegment(text=text, start_seconds=start, end_seconds=end)
                for text, start, end in (segments or [])
            ],
        ),
    )


def test_routing_preserves_clear_source_speech_without_voiceover():
    source = analysis(segments=[("它今天终于学会握手了", 0, 4)])

    decision = AudioRoutingService().decide(
        [source],
        narration_text="这段文本不应该被合成。",
        voiceover=None,
    )

    assert decision.mode == "original"
    assert decision.voiceover_path is None
    assert decision.original_gain_db == 0
    assert "有效人声" in decision.reason


def test_planned_mode_can_be_checked_before_requesting_tts():
    router = AudioRoutingService()

    assert router.planned_mode([analysis(segments=[("完整口播", 0, 4)])]) == "original"
    assert router.planned_mode([analysis(segments=[("汪", 1, 1.4)])]) == "mixed"
    assert router.planned_mode([analysis(segments=[])]) == "narration"


def test_product_explainer_uses_narration_when_source_speech_is_only_partial():
    router = AudioRoutingService()
    source = analysis(duration=10, segments=[("现场只有一句简短介绍", 0, 4)])

    assert router.planned_mode([source], content_type="商品介绍") == "mixed"
    assert router.planned_mode([source], content_type="通用短视频") == "original"


def test_routing_mixes_voiceover_when_source_speech_is_brief(tmp_path: Path):
    voice = TTSResult(
        path=(tmp_path / "voice.mp3").resolve(),
        duration_seconds=4,
        voice_type="zh_female_vv_uranus_bigtts",
    )
    source = analysis(segments=[("汪", 1, 1.4)])

    decision = AudioRoutingService().decide(
        [source],
        narration_text="它假装听不懂。直到零食出现，它立刻坐得笔直。",
        voiceover=voice,
    )

    assert decision.mode == "mixed"
    assert decision.original_gain_db == -10
    assert decision.voiceover_path == str(voice.path)
    assert decision.voice_type == voice.voice_type
    assert decision.captions
    assert decision.captions[-1].end_seconds <= 4


def test_routing_uses_narration_for_stock_footage_without_speech(tmp_path: Path):
    voice = TTSResult(
        path=(tmp_path / "voice.mp3").resolve(),
        duration_seconds=5,
        voice_type="zh_female_vv_uranus_bigtts",
    )

    decision = AudioRoutingService().decide(
        [analysis(segments=[])],
        narration_text="别看它一脸无辜，其实家里的拖鞋都是它藏的。",
        voiceover=voice,
    )

    assert decision.mode == "narration"
    assert decision.original_gain_db == -22
    assert decision.voiceover_gain_db == 0
    assert "未检测到有效人声" in decision.reason


def test_narration_captions_are_semantic_complete_and_cover_voiceover(tmp_path: Path):
    voice = TTSResult(
        path=(tmp_path / "voice.mp3").resolve(),
        duration_seconds=9,
        voice_type="zh_female_vv_uranus_bigtts",
    )
    text = "沙发不再粘毛，其实只差这一步。先逆着毛发轻轻梳开，再顺着方向带走浮毛。"

    decision = AudioRoutingService().decide(
        [analysis(segments=[])],
        narration_text=text,
        voiceover=voice,
        content_type="商品介绍",
    )

    assert decision.captions[0].start_seconds == 0
    assert decision.captions[-1].end_seconds == 9
    assert all(len(cue.text) <= 16 for cue in decision.captions)
    assert "".join(cue.text for cue in decision.captions) == text
    assert any("沙发不再粘毛" in cue.emphasis_terms for cue in decision.captions)


def test_routing_degrades_without_tts_instead_of_blocking():
    decision = AudioRoutingService().decide(
        [analysis(has_audio=False, segments=[])],
        narration_text="本应生成旁白。",
        voiceover=None,
    )

    assert decision.mode == "original"
    assert decision.voiceover_path is None
    assert decision.warning == "旁白需要生成但 TTS 不可用，已保留原始音轨继续处理。"
