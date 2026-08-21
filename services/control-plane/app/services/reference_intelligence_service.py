from __future__ import annotations

from app.schemas.editing import (
    MediaAnalysis,
    ReferencePacingProfile,
    ReferenceShotGroup,
    ReferenceVideoBrief,
    SceneInterval,
)


def _overlaps(start: float, end: float, other_start: float, other_end: float) -> bool:
    return max(start, other_start) < min(end, other_end)


class ReferenceIntelligenceService:
    @staticmethod
    def _scenes(analysis: MediaAnalysis) -> list[SceneInterval]:
        if analysis.scenes:
            return analysis.scenes
        return [SceneInterval(start_seconds=0, end_seconds=analysis.duration_seconds, score=0)]

    def build(self, analysis: MediaAnalysis, *, source_name: str) -> ReferenceVideoBrief:
        scenes = self._scenes(analysis)
        durations = [scene.end_seconds - scene.start_seconds for scene in scenes]
        average = sum(durations) / len(durations)
        cuts_per_minute = len(scenes) * 60 / analysis.duration_seconds
        if average <= 2.4 or cuts_per_minute >= 25:
            pace = "rapid"
        elif average >= 5 or cuts_per_minute <= 12:
            pace = "steady"
        else:
            pace = "balanced"
        preferred = min(6, max(0.6, average))
        hook_window = min(3, max(0.5, scenes[0].end_seconds))
        transcript = analysis.transcript.text.strip()
        ocr = list(
            dict.fromkeys(
                text.strip()
                for frame in analysis.frames
                for text in frame.ocr_texts
                if text.strip()
            )
        )
        if transcript:
            content_summary = transcript[:240]
        elif ocr:
            content_summary = "画面文字：" + "、".join(ocr[:8])
        else:
            content_summary = "未检测到可靠语音或画面文字，仅使用镜头结构作为参考。"
        orientation = "竖屏" if analysis.height > analysis.width else "横屏"
        caption_density = sum(bool(frame.ocr_texts) for frame in analysis.frames) / max(1, len(analysis.frames))
        shot_groups = []
        for index, scene in enumerate(scenes[:20]):
            speech = [
                segment.text
                for segment in analysis.transcript.segments
                if _overlaps(
                    scene.start_seconds,
                    scene.end_seconds,
                    segment.start_seconds,
                    segment.end_seconds,
                )
            ]
            frame = min(
                analysis.frames,
                key=lambda item: abs(item.timestamp_seconds - (scene.start_seconds + scene.end_seconds) / 2),
                default=None,
            )
            frame_text = "、".join(frame.ocr_texts[:4]) if frame and frame.ocr_texts else "无可读叠字"
            shot_groups.append(
                ReferenceShotGroup(
                    start_seconds=scene.start_seconds,
                    end_seconds=scene.end_seconds,
                    subject="口播主体（需多模态模型确认人物与物体）" if speech else "视觉主体待多模态确认",
                    subject_motion="口播驱动的动作段" if speech else "无语音动作段，运动类型待确认",
                    scene=f"场景组 {index + 1}；叠字：{frame_text}",
                    spatial_framing=f"{orientation} {analysis.width}×{analysis.height}；景别与主体位置待确认",
                    camera="结构分析确认切点；机位、焦段和运镜需多模态复核",
                    evidence=[
                        f"scene_score={scene.score:.3f}",
                        f"duration={scene.end_seconds - scene.start_seconds:.3f}s",
                    ],
                )
            )
        style_summary = (
            f"{orientation}、{pace} 节奏，平均镜头 {average:.2f} 秒，"
            f"约 {cuts_per_minute:.1f} 切/分钟，画面文字覆盖率 {caption_density:.0%}。"
        )
        structure_summary = (
            f"共 {len(scenes)} 个结构镜头；开场参考窗口 {hook_window:.2f} 秒；"
            f"建议单镜头约 {preferred:.2f} 秒。"
        )
        warnings = []
        if not transcript:
            warnings.append("参考片缺少可靠转写，内容语义未作为剪辑依据。")
        warnings.append("人物、物体、景别和运镜为待复核项；本地结构分析不伪装成视觉语义理解。")
        return ReferenceVideoBrief(
            source_name=source_name,
            duration_seconds=analysis.duration_seconds,
            content_summary=content_summary,
            style_summary=style_summary,
            structure_summary=structure_summary,
            pacing=ReferencePacingProfile(
                average_scene_seconds=round(average, 3),
                cuts_per_minute=round(cuts_per_minute, 3),
                preferred_clip_seconds=round(preferred, 3),
                hook_window_seconds=round(hook_window, 3),
                pace=pace,
            ),
            shot_groups=shot_groups,
            keep_patterns=[
                f"保留约 {preferred:.2f} 秒的镜头节奏",
                f"在前 {hook_window:.2f} 秒完成信息钩子",
                "保留结构、能量和字幕密度，不复刻人物、文案或素材",
            ],
            change_requirements=[
                "主题、人物、品牌、文案和视觉资产必须替换为当前任务内容。",
                "不得复用、下载或嵌入参考片原始素材。",
                "无法由本地结构数据证明的视觉判断必须留待多模态模型或人工复核。",
            ],
            warnings=warnings,
        )
