from __future__ import annotations

from pathlib import Path

from app.schemas.editing import (
    FrameEvidence,
    MediaAnalysis,
    SceneInterval,
    TranscriptResult,
    TranscriptSegment,
)
from app.services.reference_intelligence_service import ReferenceIntelligenceService


def test_reference_service_builds_five_aspect_brief_and_pacing(tmp_path: Path):
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"reference")
    analysis = MediaAnalysis(
        material_id="reference",
        source_path=str(source),
        duration_seconds=6,
        width=1080,
        height=1920,
        has_audio=True,
        transcript=TranscriptResult(
            language="zh",
            provider="volcano_bigasr",
            model="volc.bigasr.auc_turbo",
            duration_seconds=6,
            segments=[
                TranscriptSegment(
                    text="先看最终效果，再讲三个步骤。",
                    start_seconds=0,
                    end_seconds=3,
                    confidence=0.95,
                )
            ],
        ),
        scenes=[
            SceneInterval(start_seconds=0, end_seconds=1.5, score=0.8),
            SceneInterval(start_seconds=1.5, end_seconds=3, score=0.7),
            SceneInterval(start_seconds=3, end_seconds=4.5, score=0.6),
            SceneInterval(start_seconds=4.5, end_seconds=6, score=0.7),
        ],
        frames=[
            FrameEvidence(
                timestamp_seconds=0.5,
                image_path=str(tmp_path / "frame.jpg"),
                width=1080,
                height=1920,
                brightness=120,
                contrast=48,
                sharpness=420,
                ocr_texts=["三步完成"],
            )
        ],
    )

    brief = ReferenceIntelligenceService().build(analysis, source_name="爆款参考.mp4")

    assert brief.source_name == "爆款参考.mp4"
    assert brief.provider == "local_structural"
    assert brief.pacing.pace == "rapid"
    assert brief.pacing.preferred_clip_seconds == 1.5
    assert brief.pacing.hook_window_seconds == 1.5
    assert len(brief.shot_groups) == 4
    assert all(item.subject and item.subject_motion for item in brief.shot_groups)
    assert all(item.scene and item.spatial_framing and item.camera for item in brief.shot_groups)
    assert "先看最终效果" in brief.content_summary
    assert any("不得复用" in item for item in brief.change_requirements)
