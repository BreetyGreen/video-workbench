from __future__ import annotations

from dataclasses import dataclass

from app.schemas.analysis import EditRecipe
from app.schemas.editing import (
    AudioMixPlan,
    CaptionCue,
    CoverPlan,
    CourseRuleTrace,
    EditingTimeline,
    MediaAnalysis,
    ReferenceVideoBrief,
    SilenceInterval,
    TimelineClip,
)
from app.services.audio_routing_service import AudioRoutingDecision
from app.services.course_recipe_service import CourseEditingPolicy, CourseRule


FILLER_WORDS = {"嗯", "呃", "啊", "额", "um", "uh", "erm", "like"}


@dataclass(frozen=True)
class Candidate:
    material_id: str
    source_path: str
    start: float
    end: float
    score: float
    reason: str
    has_audio: bool

    @property
    def duration(self) -> float:
        return self.end - self.start


def invert_intervals(
    duration_seconds: float,
    removed: list[SilenceInterval],
    *,
    minimum_keep_seconds: float = 0.3,
) -> list[tuple[float, float]]:
    cursor = 0.0
    kept = []
    for interval in sorted(removed, key=lambda item: item.start_seconds):
        start = min(duration_seconds, max(cursor, interval.start_seconds))
        if start - cursor >= minimum_keep_seconds:
            kept.append((round(cursor, 6), round(start, 6)))
        cursor = min(duration_seconds, max(cursor, interval.end_seconds))
    if duration_seconds - cursor >= minimum_keep_seconds:
        kept.append((round(cursor, 6), round(duration_seconds, 6)))
    return kept


def _is_filler(text: str) -> bool:
    normalized = text.strip().lower().strip("，。！？,.!?~ ")
    return normalized in FILLER_WORDS


def _visual_score(analysis: MediaAnalysis) -> float:
    if not analysis.frames:
        return 0.5
    sharpness = sum(item.sharpness for item in analysis.frames) / len(analysis.frames)
    contrast = sum(item.contrast for item in analysis.frames) / len(analysis.frames)
    brightness = sum(item.brightness for item in analysis.frames) / len(analysis.frames)
    exposure = max(0.0, 1.0 - abs(brightness - 128) / 128)
    return min(2.0, sharpness / 500 + contrast / 128 + exposure * 0.5)


def _split_interval(start: float, end: float, maximum_seconds: float = 4.5) -> list[tuple[float, float]]:
    output = []
    cursor = start
    while end - cursor >= 0.3:
        chunk_end = min(end, cursor + maximum_seconds)
        output.append((cursor, chunk_end))
        cursor = chunk_end
    return output


def _overlap_ratio(left: Candidate, right: Candidate) -> float:
    if left.material_id != right.material_id:
        return 0
    overlap = max(0.0, min(left.end, right.end) - max(left.start, right.start))
    return overlap / max(0.001, min(left.duration, right.duration))


class TimelinePlanner:
    def __init__(
        self,
        *,
        max_automatic_seconds: float = 180,
        speech_padding_seconds: float = 0.15,
    ):
        self.max_automatic_seconds = max_automatic_seconds
        self.speech_padding_seconds = speech_padding_seconds

    def _candidates(
        self,
        analyses: list[MediaAnalysis],
        *,
        maximum_clip_seconds: float = 3,
    ) -> list[Candidate]:
        candidates: list[Candidate] = []
        for analysis in analyses:
            visual = _visual_score(analysis)
            for segment in analysis.transcript.segments:
                if _is_filler(segment.text):
                    continue
                start = max(0, segment.start_seconds - self.speech_padding_seconds)
                end = min(analysis.duration_seconds, segment.end_seconds + self.speech_padding_seconds)
                for part_start, part_end in _split_interval(
                    start,
                    end,
                    maximum_seconds=maximum_clip_seconds,
                ):
                    early_bonus = 1.0 if part_start < 8 else 0
                    candidates.append(
                        Candidate(
                            material_id=analysis.material_id,
                            source_path=analysis.source_path,
                            start=part_start,
                            end=part_end,
                            score=5 + segment.confidence * 2 + visual + early_bonus,
                            reason=f"speech:{segment.text[:32]}",
                            has_audio=analysis.has_audio,
                        )
                    )
            for scene in analysis.scenes:
                safe_scene_start = scene.start_seconds
                if scene.start_seconds <= 0.05 and scene.end_seconds - scene.start_seconds < 0.8:
                    continue
                if scene.start_seconds <= 0.05 and scene.end_seconds - scene.start_seconds >= 1.1:
                    safe_scene_start = min(scene.end_seconds - 0.3, 0.8)
                for start, end in _split_interval(
                    safe_scene_start,
                    scene.end_seconds,
                    maximum_seconds=maximum_clip_seconds,
                ):
                    candidate = Candidate(
                        material_id=analysis.material_id,
                        source_path=analysis.source_path,
                        start=start,
                        end=end,
                        score=1 + visual + scene.score + (0.75 if start < 8 else 0),
                        reason=(
                            "visual:scene_change"
                            if scene.start_seconds > 0
                            else "visual:opening_trimmed"
                            if safe_scene_start > scene.start_seconds
                            else "visual:opening"
                        ),
                        has_audio=analysis.has_audio,
                    )
                    if not any(_overlap_ratio(candidate, existing) > 0.8 for existing in candidates):
                        candidates.append(candidate)
        return candidates

    def plan(
        self,
        analyses: list[MediaAnalysis],
        *,
        title: str,
        target_seconds: float = 30,
        recipe: EditRecipe | None = None,
        bgm_path: str | None = None,
        reference_brief: ReferenceVideoBrief | None = None,
        audio_decision: AudioRoutingDecision | None = None,
        course_policy: CourseEditingPolicy | None = None,
    ) -> EditingTimeline:
        if not analyses:
            raise ValueError("At least one media analysis is required")
        requested = (
            min(float(recipe.target_duration_seconds), target_seconds)
            if recipe is not None
            else target_seconds
        )
        target = min(max(0.3, requested), self.max_automatic_seconds)
        maximum_clip_seconds = (
            reference_brief.pacing.preferred_clip_seconds if reference_brief else 3
        )
        if course_policy is not None and course_policy.maximum_clip_seconds is not None:
            maximum_clip_seconds = min(maximum_clip_seconds, course_policy.maximum_clip_seconds)
        candidates = self._candidates(
            analyses,
            maximum_clip_seconds=maximum_clip_seconds,
        )
        if not candidates:
            raise ValueError("No usable media intervals were found")

        hook_window = reference_brief.pacing.hook_window_seconds if reference_brief else 3
        hook_pool = [item for item in candidates if item.start < hook_window] or candidates
        if course_policy is not None and course_policy.hook_keywords:
            def course_hook_score(item: Candidate) -> tuple[int, float, float]:
                searchable = f"{item.reason} {item.source_path}".lower()
                matches = sum(keyword.lower() in searchable for keyword in course_policy.hook_keywords)
                return matches, item.score, -item.start

            hook = max(hook_pool, key=course_hook_score)
        else:
            hook = max(hook_pool, key=lambda item: (item.score, -item.start))
        selected = [hook]
        remaining = [item for item in candidates if item != hook and _overlap_ratio(item, hook) < 0.8]
        while sum(item.duration for item in selected) < target - 0.001 and remaining:
            previous_material = selected[-1].material_id
            alternatives = [item for item in remaining if item.material_id != previous_material]
            pool = alternatives or remaining
            chosen = max(pool, key=lambda item: (item.score, -item.start))
            selected.append(chosen)
            remaining = [item for item in remaining if item != chosen and _overlap_ratio(item, chosen) < 0.8]

        clips = []
        cursor = 0.0
        hook_rule = course_policy.first("hook") if course_policy else None
        pacing_rule = course_policy.first("pacing") if course_policy else None
        cta_rule = course_policy.first("cta") if course_policy else None
        for index, candidate in enumerate(selected):
            available = target - cursor
            if available < 0.3:
                break
            duration = min(candidate.duration, available)
            applied_rule_ids: list[str] = []
            if index == 0 and hook_rule is not None:
                applied_rule_ids.append(hook_rule.id)
            if pacing_rule is not None:
                applied_rule_ids.append(pacing_rule.id)
            if index == len(selected) - 1 and cta_rule is not None:
                applied_rule_ids.append(cta_rule.id)
            clip = TimelineClip(
                material_id=candidate.material_id,
                source_path=candidate.source_path,
                source_start_seconds=candidate.start,
                source_end_seconds=candidate.start + duration,
                timeline_start_seconds=cursor,
                timeline_end_seconds=cursor + duration,
                score=candidate.score,
                reason=f"hook:{candidate.reason}" if index == 0 else candidate.reason,
                has_audio=candidate.has_audio,
                applied_rule_ids=applied_rule_ids,
            )
            clips.append(clip)
            cursor += duration

        analysis_by_id = {item.material_id: item for item in analyses}
        captions = []
        for clip in clips:
            analysis = analysis_by_id[clip.material_id]
            for segment in analysis.transcript.segments:
                if _is_filler(segment.text):
                    continue
                overlap_start = max(segment.start_seconds, clip.source_start_seconds)
                overlap_end = min(segment.end_seconds, clip.source_end_seconds)
                if overlap_end - overlap_start < 0.05:
                    continue
                cue_start = clip.timeline_start_seconds + overlap_start - clip.source_start_seconds
                cue_end = clip.timeline_start_seconds + overlap_end - clip.source_start_seconds
                captions.append(
                    CaptionCue(
                        material_id=clip.material_id,
                        text=segment.text.strip(),
                        start_seconds=cue_start,
                        end_seconds=min(cursor, cue_end),
                        source_start_seconds=overlap_start,
                        source_end_seconds=overlap_end,
                    )
                )
        captions.sort(key=lambda item: (item.start_seconds, item.end_seconds))
        if audio_decision is not None and audio_decision.voiceover_path:
            voice_captions = []
            for cue in audio_decision.captions:
                values = cue.model_dump() if isinstance(cue, CaptionCue) else cue
                if values["start_seconds"] >= cursor:
                    continue
                values = {**values, "end_seconds": min(values["end_seconds"], cursor)}
                if values["end_seconds"] > values["start_seconds"]:
                    voice_captions.append(CaptionCue(**values))
            captions = voice_captions

        removed_silence = sum(
            max(0, interval.end_seconds - interval.start_seconds)
            for analysis in analyses
            for interval in analysis.silences
            if interval.end_seconds - interval.start_seconds >= 0.8
        )
        cover_clip = clips[0]
        rule_trace: list[CourseRuleTrace] = []

        def append_trace(rule: CourseRule | None, *, segment_id: str, decision: str, before: str, after: str) -> None:
            if rule is None:
                return
            rule_trace.append(
                CourseRuleTrace(
                    segment_id=segment_id,
                    rule_id=rule.id,
                    rule_category=rule.category,
                    tutorial_asset_id=rule.source_asset_id,
                    tutorial_start_ms=rule.source_start_ms,
                    tutorial_end_ms=rule.source_end_ms,
                    evidence_text=rule.evidence_text,
                    decision=decision,
                    before=before,
                    after=after,
                )
            )

        if clips:
            append_trace(
                hook_rule,
                segment_id=f"clip-1:{clips[0].material_id}",
                decision="按教程钩子关键词选择首镜头",
                before="按本地综合质量分选择首镜头",
                after=f"首镜头选择 {clips[0].material_id}，{clips[0].duration_seconds:.2f} 秒",
            )
            append_trace(
                pacing_rule,
                segment_id="timeline",
                decision="按教程限制单镜头最大时长",
                before="本地默认单镜头最多 3.00 秒",
                after=f"单镜头最多 {maximum_clip_seconds:.2f} 秒",
            )
            append_trace(
                cta_rule,
                segment_id=f"clip-{len(clips)}:{clips[-1].material_id}",
                decision="把结尾片段标记为行动引导承载镜头",
                before="按质量分完成尾镜头选择",
                after=f"尾镜头使用 {clips[-1].material_id}",
            )

        timeline = EditingTimeline(
            title=title.strip() or "video",
            target_duration_seconds=target,
            actual_duration_seconds=cursor,
            engine=(
                "course_learned"
                if course_policy is not None
                else "reference_guided"
                if reference_brief is not None
                else "dify_enhanced"
                if recipe is not None
                else "local_intelligent"
            ),
            clips=clips,
            captions=captions,
            audio=AudioMixPlan(
                mode=audio_decision.mode if audio_decision else "original",
                original_gain_db=audio_decision.original_gain_db if audio_decision else 0,
                voiceover_path=audio_decision.voiceover_path if audio_decision else None,
                voiceover_gain_db=audio_decision.voiceover_gain_db if audio_decision else 0,
                voice_type=audio_decision.voice_type if audio_decision else None,
                voiceover_duration_seconds=audio_decision.voiceover_duration_seconds if audio_decision else 0,
                decision_reason=audio_decision.reason if audio_decision else "",
                bgm_path=bgm_path,
            ),
            cover=CoverPlan(
                material_id=cover_clip.material_id,
                source_path=cover_clip.source_path,
                source_timestamp_seconds=(
                    cover_clip.source_start_seconds + min(1.0, cover_clip.duration_seconds / 2)
                ),
                title=title.strip() or "video",
            ),
            removed_silence_seconds=removed_silence,
            source_count=len({clip.material_id for clip in clips}),
            rule_trace=rule_trace,
        )
        validate_timeline(timeline, analyses)
        return timeline


def validate_timeline(timeline: EditingTimeline, analyses: list[MediaAnalysis]) -> None:
    by_id = {item.material_id: item for item in analyses}
    cursor = 0.0
    seen = set()
    for clip in timeline.clips:
        analysis = by_id.get(clip.material_id)
        if analysis is None:
            raise ValueError(f"Unknown timeline material: {clip.material_id}")
        if clip.source_path != analysis.source_path:
            raise ValueError("Timeline source path does not match analyzed media")
        if clip.source_start_seconds < 0 or clip.source_end_seconds > analysis.duration_seconds + 0.02:
            raise ValueError("Timeline clip exceeds source bounds")
        if abs(clip.timeline_start_seconds - cursor) > 0.02:
            raise ValueError("Timeline clips must start at zero and remain contiguous")
        key = (clip.material_id, round(clip.source_start_seconds, 3), round(clip.source_end_seconds, 3))
        if key in seen:
            raise ValueError("Timeline repeats the same source interval")
        seen.add(key)
        cursor = clip.timeline_end_seconds
    if abs(cursor - timeline.actual_duration_seconds) > 0.02:
        raise ValueError("Timeline actual duration does not match clips")
    for cue in timeline.captions:
        if cue.start_seconds < 0 or cue.end_seconds > timeline.actual_duration_seconds + 0.02:
            raise ValueError("Caption exceeds timeline bounds")
