from __future__ import annotations

from pathlib import Path

import pytest

from app.models import EditingRecipe, EditingRule
from app.services.course_recipe_service import CourseRecipeService
from app.services.timeline_service import TimelinePlanner
from app.schemas.editing import (
    FrameEvidence,
    MediaAnalysis,
    SceneInterval,
    TranscriptResult,
    TranscriptSegment,
)


def _analysis(tmp_path: Path, material_id: str, text: str, confidence: float) -> MediaAnalysis:
    source = tmp_path / f"{material_id}.mp4"
    source.write_bytes(b"video")
    return MediaAnalysis(
        material_id=material_id,
        source_path=str(source),
        duration_seconds=6,
        width=1080,
        height=1920,
        has_audio=True,
        transcript=TranscriptResult(
            duration_seconds=6,
            segments=[
                TranscriptSegment(
                    text=text,
                    start_seconds=0.2,
                    end_seconds=5.6,
                    confidence=confidence,
                )
            ],
        ),
        scenes=[SceneInterval(start_seconds=0, end_seconds=6, score=0.5)],
        frames=[
            FrameEvidence(
                timestamp_seconds=0.2,
                image_path=str(tmp_path / f"{material_id}.jpg"),
                width=1080,
                height=1920,
                brightness=120,
                contrast=45,
                sharpness=330,
            )
        ],
    )


def _recipe_and_rules() -> tuple[EditingRecipe, list[EditingRule]]:
    recipe = EditingRecipe(
        id="recipe-1",
        course_id="course-1",
        version=1,
        title="宠物护理课",
        tutorial_asset_id="tutorial-1",
        transcript_sha256="a" * 64,
    )
    rules = [
        EditingRule(
            id="hook-rule",
            recipe_id=recipe.id,
            category="hook",
            instruction="前三秒先放掉毛问题特写",
            evidence_text="前三秒先放掉毛问题特写",
            confidence=0.96,
            source_asset_id="tutorial-1",
            source_start_ms=400,
            source_end_ms=3000,
        ),
        EditingRule(
            id="pace-rule",
            recipe_id=recipe.id,
            category="pacing",
            instruction="单镜头不要超过 1.2 秒",
            evidence_text="单镜头不要超过 1.2 秒",
            confidence=0.93,
            source_asset_id="tutorial-1",
            source_start_ms=3100,
            source_end_ms=5200,
        ),
        EditingRule(
            id="cta-rule",
            recipe_id=recipe.id,
            category="cta",
            instruction="结尾给出自然行动提示",
            evidence_text="结尾给出自然行动提示",
            confidence=0.9,
            source_asset_id="tutorial-1",
            source_start_ms=5300,
            source_end_ms=7200,
        ),
    ]
    return recipe, rules


def test_course_policy_changes_timeline_and_produces_cited_rule_trace(tmp_path: Path) -> None:
    normal = _analysis(tmp_path, "normal", "普通使用展示", 0.99)
    problem = _analysis(tmp_path, "problem", "沙发掉毛问题特写", 0.82)
    recipe, rules = _recipe_and_rules()
    service = CourseRecipeService()
    policy = service.compile(recipe, rules)
    planner = TimelinePlanner()

    baseline = planner.plan([normal, problem], title="宠物护理", target_seconds=5)
    learned = planner.plan(
        [normal, problem],
        title="宠物护理",
        target_seconds=5,
        course_policy=policy,
    )
    comparison = service.compare(baseline, learned, policy)

    assert baseline.clips[0].material_id == "normal"
    assert learned.clips[0].material_id == "problem"
    assert max(clip.duration_seconds for clip in learned.clips) <= 1.21
    assert comparison["status"] == "pass"
    assert len(comparison["meaningful_changes"]) >= 2
    assert {trace.rule_id for trace in learned.rule_trace} >= {"hook-rule", "pace-rule", "cta-rule"}
    assert all(trace.tutorial_start_ms is not None for trace in learned.rule_trace)
    assert all(trace.evidence_text for trace in learned.rule_trace)
    assert all(trace.rule_id in {rule.id for rule in rules} for trace in learned.rule_trace)


def test_unchanged_course_timeline_fails_closed(tmp_path: Path) -> None:
    source = _analysis(tmp_path, "only", "普通展示", 0.9)
    recipe = EditingRecipe(
        id="recipe-2",
        course_id="course-2",
        title="只有字幕的课程",
        tutorial_asset_id="tutorial-2",
        transcript_sha256="b" * 64,
    )
    rule = EditingRule(
        id="caption-rule",
        recipe_id=recipe.id,
        category="captions",
        instruction="字幕每行十四个字",
        evidence_text="字幕每行十四个字",
        confidence=0.9,
        source_asset_id="tutorial-2",
        source_start_ms=0,
        source_end_ms=1000,
    )
    service = CourseRecipeService()
    policy = service.compile(recipe, [rule])
    planner = TimelinePlanner()
    baseline = planner.plan([source], title="普通展示", target_seconds=4)
    learned = planner.plan([source], title="普通展示", target_seconds=4, course_policy=policy)

    with pytest.raises(ValueError, match="course_rules_not_applied"):
        service.compare(baseline, learned, policy)
