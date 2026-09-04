from __future__ import annotations

from dataclasses import dataclass
import re

from app.models import EditingRecipe, EditingRule
from app.schemas.editing import EditingTimeline


ALLOWED_COURSE_RULES = {
    "hook",
    "pacing",
    "structure",
    "captions",
    "audio",
    "cta",
    "negative",
    "closeup",
    "comparison",
}
KEYWORD_VOCABULARY = (
    "问题",
    "掉毛",
    "结果",
    "效果",
    "特写",
    "对比",
    "佩戴",
    "使用后",
    "行动",
    "下单",
    "收藏",
)
SECONDS = re.compile(r"(?P<seconds>\d+(?:\.\d+)?)\s*秒")
CHINESE_SECONDS = {
    "零点八秒": 0.8,
    "一秒": 1.0,
    "一点二秒": 1.2,
    "一点五秒": 1.5,
    "二秒": 2.0,
    "两秒": 2.0,
    "二点五秒": 2.5,
    "三秒": 3.0,
}


@dataclass(frozen=True)
class CourseRule:
    id: str
    category: str
    instruction: str
    evidence_text: str
    confidence: float
    source_asset_id: str
    source_start_ms: int | None
    source_end_ms: int | None


@dataclass(frozen=True)
class CourseEditingPolicy:
    recipe_id: str
    course_id: str
    version: int
    transcript_sha256: str
    rules: tuple[CourseRule, ...]
    maximum_clip_seconds: float | None
    hook_keywords: tuple[str, ...]

    def first(self, category: str) -> CourseRule | None:
        return next((rule for rule in self.rules if rule.category == category), None)


class CourseRecipeService:
    def compile(
        self,
        recipe: EditingRecipe,
        rules: list[EditingRule],
    ) -> CourseEditingPolicy:
        if not recipe.tutorial_asset_id or not recipe.transcript_sha256:
            raise ValueError("course_recipe_evidence_required")
        compiled: list[CourseRule] = []
        maximum_clip_seconds: float | None = None
        hook_keywords: list[str] = []
        for rule in sorted(rules, key=lambda item: (item.sort_order, item.id)):
            if rule.category not in ALLOWED_COURSE_RULES:
                raise ValueError("course_rule_category_unknown")
            if not rule.evidence_text.strip():
                raise ValueError("course_rule_evidence_required")
            if not 0 <= rule.confidence <= 1:
                raise ValueError("course_rule_confidence_invalid")
            if rule.source_start_ms is not None:
                if rule.source_end_ms is None or rule.source_end_ms <= rule.source_start_ms:
                    raise ValueError("course_rule_evidence_range_invalid")
            current = CourseRule(
                id=rule.id,
                category=rule.category,
                instruction=rule.instruction.strip(),
                evidence_text=rule.evidence_text.strip(),
                confidence=rule.confidence,
                source_asset_id=rule.source_asset_id,
                source_start_ms=rule.source_start_ms,
                source_end_ms=rule.source_end_ms,
            )
            compiled.append(current)
            if rule.category == "pacing":
                matches = [float(match.group("seconds")) for match in SECONDS.finditer(rule.instruction)]
                matches.extend(
                    seconds for phrase, seconds in CHINESE_SECONDS.items() if phrase in rule.instruction
                )
                if matches:
                    candidate = min(matches)
                    if 0.3 <= candidate <= 10:
                        maximum_clip_seconds = candidate
            if rule.category == "hook":
                hook_keywords.extend(token for token in KEYWORD_VOCABULARY if token in rule.instruction)
        return CourseEditingPolicy(
            recipe_id=recipe.id,
            course_id=recipe.course_id,
            version=recipe.version,
            transcript_sha256=recipe.transcript_sha256,
            rules=tuple(compiled),
            maximum_clip_seconds=maximum_clip_seconds,
            hook_keywords=tuple(dict.fromkeys(hook_keywords)),
        )

    @staticmethod
    def _signature(timeline: EditingTimeline, *, first: bool) -> tuple[str, float]:
        clip = timeline.clips[0] if first else timeline.clips[-1]
        return clip.material_id, round(clip.source_start_seconds, 3)

    def compare(
        self,
        baseline: EditingTimeline,
        learned: EditingTimeline,
        policy: CourseEditingPolicy,
    ) -> dict[str, object]:
        baseline_average = baseline.actual_duration_seconds / len(baseline.clips)
        learned_average = learned.actual_duration_seconds / len(learned.clips)
        changes: list[str] = []
        if self._signature(baseline, first=True) != self._signature(learned, first=True):
            changes.append("hook_position")
        if abs(baseline_average - learned_average) >= 0.1:
            changes.append("average_clip_seconds")
        if len(baseline.clips) != len(learned.clips):
            changes.append("clip_count")
        if self._signature(baseline, first=False) != self._signature(learned, first=False):
            changes.append("cta_ending")
        if len(changes) < 2 or not learned.rule_trace:
            raise ValueError("course_rules_not_applied")
        known_rule_ids = {rule.id for rule in policy.rules}
        if any(trace.rule_id not in known_rule_ids for trace in learned.rule_trace):
            raise ValueError("course_rule_trace_invalid")
        return {
            "status": "pass",
            "recipe_id": policy.recipe_id,
            "recipe_version": policy.version,
            "transcript_sha256": policy.transcript_sha256,
            "meaningful_changes": changes,
            "baseline": {
                "hook": self._signature(baseline, first=True),
                "cta": self._signature(baseline, first=False),
                "clip_count": len(baseline.clips),
                "average_clip_seconds": round(baseline_average, 4),
            },
            "learned": {
                "hook": self._signature(learned, first=True),
                "cta": self._signature(learned, first=False),
                "clip_count": len(learned.clips),
                "average_clip_seconds": round(learned_average, 4),
                "trace_count": len(learned.rule_trace),
            },
        }
