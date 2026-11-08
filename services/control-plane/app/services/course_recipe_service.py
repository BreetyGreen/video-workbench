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


DIGEST_CATEGORY_BUDGET = {
    "hook": 18, "structure": 24, "pacing": 18, "captions": 12, "audio": 12,
    "cta": 10, "negative": 14, "closeup": 10, "comparison": 8,
}
DIGEST_CATEGORY_LABEL = {
    "hook": "开头/钩子", "structure": "结构与镜头匹配", "pacing": "节奏与切点", "captions": "字幕",
    "audio": "旁白/音乐/音效", "cta": "结尾引导", "negative": "禁止事项", "closeup": "特写与推近", "comparison": "对比",
}


def _digest_key(text: str) -> str:
    return re.sub(r"[\s，。、；：！？,.;:!?“”\"'（）()\[\]【】]", "", text).lower()[:40]


def rule_digest(rules: list[EditingRule], *, max_chars: int = 12000,
                budget: dict[str, int] | None = None) -> str:
    """Bounded, cited summary of a learned course for prompts.

    Full-video study can yield a thousand rules; the director only needs the
    distinct ones. Rules are grouped by category, near-duplicates (same
    normalized prefix) are collapsed, each category keeps a fixed budget in
    original order, and every line carries the lesson asset id and timecode.
    """
    budget = budget or DIGEST_CATEGORY_BUDGET
    grouped: dict[str, list[EditingRule]] = {}
    seen: set[str] = set()
    for rule in sorted(rules, key=lambda item: (item.sort_order, item.id)):
        key = _digest_key(rule.instruction)
        if not key or key in seen:
            continue
        seen.add(key)
        grouped.setdefault(rule.category, []).append(rule)
    lines: list[str] = []
    total_rules = len(rules)
    kept = 0
    for category in budget:
        items = grouped.get(category, [])[: budget[category]]
        if not items:
            continue
        lines.append(f"## {DIGEST_CATEGORY_LABEL.get(category, category)}（共 {len(grouped.get(category, []))} 条，精选 {len(items)} 条）")
        for rule in items:
            timecode = ""
            if rule.source_start_ms is not None and rule.source_end_ms is not None:
                timecode = f"，{rule.source_start_ms / 1000:.1f}-{rule.source_end_ms / 1000:.1f}秒"
            lines.append(f"- {rule.instruction.strip()}（课时 {rule.source_asset_id[:8]}{timecode}）")
            kept += 1
    for category, items in grouped.items():
        if category not in budget and items:
            lines.append(f"## {category}（{len(items)} 条，未精选）")
    header = f"课程规则精选：从 {total_rules} 条学习规则中去重后精选 {kept} 条，每条附课时与时间码；未列出的规则仍在课程库中。"
    text = header + "\n" + "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 20].rstrip() + "\n（已按长度截断）"
    return text


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
