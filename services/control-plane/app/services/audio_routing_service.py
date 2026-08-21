from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.adapters.volcano_tts import TTSResult
from app.schemas.editing import CaptionCue, MediaAnalysis
from app.services.caption_service import CaptionService


@dataclass(frozen=True)
class AudioRoutingDecision:
    mode: str
    reason: str
    original_gain_db: float = 0
    voiceover_path: str | None = None
    voiceover_gain_db: float = 0
    voice_type: str | None = None
    voiceover_duration_seconds: float = 0
    captions: list[CaptionCue] = field(default_factory=list)
    warning: str = ""


class AudioRoutingService:
    @staticmethod
    def _speech_seconds(analyses: list[MediaAnalysis]) -> float:
        return sum(
            max(0, segment.end_seconds - segment.start_seconds)
            for analysis in analyses
            for segment in analysis.transcript.segments
            if segment.text.strip()
        )

    def planned_mode(self, analyses: list[MediaAnalysis], *, content_type: str = "") -> str:
        total_duration = sum(item.duration_seconds for item in analyses)
        speech_seconds = self._speech_seconds(analyses)
        speech_ratio = speech_seconds / max(0.001, total_duration)
        guided_explainer = any(keyword in content_type.lower() for keyword in ("商品", "产品", "教程", "讲解", "带货"))
        if guided_explainer:
            if speech_seconds >= 5 and speech_ratio >= 0.65:
                return "original"
            return "mixed" if speech_seconds > 0 else "narration"
        if speech_seconds >= 2 and speech_ratio >= 0.2:
            return "original"
        return "mixed" if speech_seconds > 0 else "narration"

    @staticmethod
    def _captions(text: str, duration_seconds: float, *, content_type: str = "") -> list[CaptionCue]:
        parts = CaptionService.segment_text(text, max_chars=16)
        if not parts:
            return []
        duration = max(0.2, duration_seconds)
        weights = [max(1, len(item)) for item in parts]
        total = sum(weights)
        cursor = 0.0
        captions: list[CaptionCue] = []
        guided_explainer = any(keyword in content_type.lower() for keyword in ("商品", "产品", "教程", "讲解", "带货"))
        for index, (part, weight) in enumerate(zip(parts, weights, strict=True)):
            end = duration if index == len(parts) - 1 else cursor + duration * weight / total
            fragments = [item.rstrip("，。！？!?；;、") for item in re.findall(r"[^，。！？!?；;、]+[，。！？!?；;、]?", part)]
            emphasis = [
                fragment
                for fragment in fragments
                if guided_explainer and any(keyword in fragment for keyword in ("不再", "效果", "步骤", "卖点", "只差", "先看", "前后"))
            ]
            captions.append(
                CaptionCue(
                    material_id="voiceover",
                    text=part,
                    start_seconds=cursor,
                    end_seconds=end,
                    source_start_seconds=cursor,
                    source_end_seconds=end,
                    emphasis_terms=emphasis,
                    placement="top" if guided_explainer and index == 0 else "bottom",
                )
            )
            cursor = end
        return captions

    def decide(
        self,
        analyses: list[MediaAnalysis],
        *,
        narration_text: str,
        voiceover: TTSResult | None,
        content_type: str = "",
    ) -> AudioRoutingDecision:
        speech_seconds = self._speech_seconds(analyses)
        planned_mode = self.planned_mode(analyses, content_type=content_type)
        if planned_mode == "original":
            return AudioRoutingDecision(
                mode="original",
                reason=f"检测到 {speech_seconds:.1f} 秒有效人声，保留原声。",
            )

        reason = (
            f"仅检测到 {speech_seconds:.1f} 秒有效人声，使用短旁白补充叙事。"
            if planned_mode == "mixed"
            else "未检测到有效人声，使用旁白建立完整叙事。"
        )
        if not narration_text.strip() or voiceover is None:
            return AudioRoutingDecision(
                mode="original",
                reason=reason,
                warning="旁白需要生成但 TTS 不可用，已保留原始音轨继续处理。",
            )
        return AudioRoutingDecision(
            mode=planned_mode,
            reason=reason,
            original_gain_db=-10 if planned_mode == "mixed" else -22,
            voiceover_path=str(voiceover.path),
            voiceover_gain_db=0,
            voice_type=voiceover.voice_type,
            voiceover_duration_seconds=voiceover.duration_seconds,
            captions=self._captions(narration_text.strip(), voiceover.duration_seconds, content_type=content_type),
        )
