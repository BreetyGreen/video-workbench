from __future__ import annotations

from pathlib import Path
import hashlib
import json

from app import models
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    Course,
    CourseAsset,
    CourseAssetRole,
    EditingRecipe,
    EditingRule,
    RightsStatus,
    TutorialSegment,
    TutorialSegmentType,
)
from app.services.tutorial_understanding_service import TutorialUnderstandingService
from app.schemas.editing import FrameEvidence, MediaAnalysis, SceneInterval, TranscriptResult, TranscriptSegment


class FakeRoutedTranscriber:
    def __init__(self, transcript: TranscriptResult):
        self.transcript = transcript
        self.calls: list[tuple[Path, str, bool]] = []

    def transcribe(
        self,
        source: Path,
        *,
        quality_profile: str,
        cloud_processing_allowed: bool,
    ) -> TranscriptResult:
        self.calls.append((source, quality_profile, cloud_processing_allowed))
        return self.transcript


class FakeTutorialMediaAnalyzer:
    def __init__(self, analysis: MediaAnalysis):
        self.analysis = analysis
        self.calls: list[tuple[Path, str, Path, str, bool]] = []

    def analyze(
        self,
        source: Path,
        *,
        material_id: str,
        output_dir: Path,
        quality_profile: str,
        cloud_processing_allowed: bool,
    ) -> MediaAnalysis:
        self.calls.append((source, material_id, output_dir, quality_profile, cloud_processing_allowed))
        return self.analysis


def test_tutorial_segment_contract_is_persisted_separately_from_rules() -> None:
    assert hasattr(models, "TutorialSegmentType")
    assert hasattr(models, "TutorialSegment")
    assert {
        item.value for item in models.TutorialSegmentType
    } == {"lecture", "software_operation", "finished_example", "intro_outro", "unknown"}


def test_single_editor_brand_ocr_is_strong_software_operation_evidence() -> None:
    segment_type, confidence, cues = TutorialUnderstandingService()._classify(
        text="",
        ocr_texts=("CAPCUT",),
        previous_type=TutorialSegmentType.UNKNOWN,
        transcript_confidence=0,
    )

    assert segment_type == TutorialSegmentType.SOFTWARE_OPERATION
    assert confidence >= 0.9
    assert "operation:capcut" in cues


def test_spoken_editor_brand_alone_does_not_hide_a_lecture_rule() -> None:
    segment_type, confidence, cues = TutorialUnderstandingService()._classify(
        text="在剪映里，前三秒先展示结果作为钩子",
        ocr_texts=(),
        previous_type=TutorialSegmentType.UNKNOWN,
        transcript_confidence=0.95,
    )

    assert segment_type == TutorialSegmentType.LECTURE
    assert confidence >= 0.9
    assert "lecture:先展示" in cues


def test_finished_example_sales_copy_stays_example_until_explicit_lesson_reentry() -> None:
    service = TutorialUnderstandingService()
    segment_type, confidence, cues = service._classify(
        text="这顶帽子需要搭配浅色外套，字幕写不要错过，结尾立即下单",
        ocr_texts=(),
        previous_type=TutorialSegmentType.FINISHED_EXAMPLE,
        transcript_confidence=0.97,
    )

    assert segment_type == TutorialSegmentType.FINISHED_EXAMPLE
    assert confidence <= 0.86
    assert cues == ("continuation:finished_example",)

    segment_type, confidence, cues = service._classify(
        text="接下来讲解字幕规则",
        ocr_texts=("课程讲解",),
        previous_type=TutorialSegmentType.FINISHED_EXAMPLE,
        transcript_confidence=0.94,
    )

    assert segment_type == TutorialSegmentType.LECTURE
    assert confidence >= 0.9
    assert "lecture_reentry:接下来讲解" in cues


def test_silent_visual_gaps_are_kept_even_without_detected_scene_cuts() -> None:
    transcript = TranscriptResult(
        language="zh",
        duration_seconds=10.0,
        segments=[],
    )
    analysis = MediaAnalysis(
        material_id="static-screen-recording",
        source_path="tutorial.mp4",
        duration_seconds=10.0,
        width=1920,
        height=1080,
        has_audio=True,
        transcript=transcript,
        scenes=[],
        frames=[],
    )

    segments = TutorialUnderstandingService()._insert_visual_gaps(
        [
            ("开场讲解", 0, 2000, 1001, 0.9),
            ("继续讲解", 6000, 8000, 2001, 0.9),
        ],
        analysis,
    )

    assert ("", 2000, 6000, 900001, 0.0) in segments
    assert ("", 8000, 10000, 900002, 0.0) in segments


def test_decimal_seconds_are_not_split_into_separate_tutorial_rules() -> None:
    transcript = TranscriptResult(
        language="zh",
        duration_seconds=4.0,
        segments=[
            TranscriptSegment(
                text="单镜头不要超过1.2秒，连续切换不同景别。",
                start_seconds=0,
                end_seconds=4,
                confidence=0.95,
            )
        ],
    )

    segments = TutorialUnderstandingService()._split_transcript(transcript)

    assert [item[0] for item in segments] == ["单镜头不要超过1.2秒，连续切换不同景别"]


def test_sentence_periods_after_integer_or_decimal_numbers_still_split_rules() -> None:
    transcript = TranscriptResult(
        language="zh",
        duration_seconds=8.0,
        segments=[
            TranscriptSegment(
                text="镜头控制为1. 下一步添加字幕. Keep it under 1.2. Then add captions.",
                start_seconds=0,
                end_seconds=8,
                confidence=0.9,
            )
        ],
    )

    segments = TutorialUnderstandingService()._split_transcript(transcript)

    assert [item[0] for item in segments] == [
        "镜头控制为1",
        "下一步添加字幕",
        "Keep it under 1.2",
        "Then add captions",
    ]


def test_plain_text_tutorial_produces_cited_editing_recipe(tmp_path: Path) -> None:
    tutorial_path = tmp_path / "tutorial.txt"
    tutorial_path.write_text(
        "0-3 秒先展示使用后的效果，制造疑问钩子。\n"
        "3-12 秒单镜头不要超过 2.5 秒。\n"
        "字幕每行不要超过 14 个汉字。\n"
        "背景音乐低于旁白并保留有信息量的原声。\n"
        "15-20 秒给出自然的行动提示，不使用夸张承诺。\n",
        encoding="utf-8",
    )
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        course = Course(title="宠物课", source_type="fixture", source_message_id="tutorial-1")
        session.add(course)
        session.commit()
        tutorial = CourseAsset(
            course_id=course.id,
            role=CourseAssetRole.TUTORIAL,
            original_name="tutorial.txt",
            stored_path=str(tutorial_path),
            mime_type="text/plain",
            size_bytes=tutorial_path.stat().st_size,
            sha256="a" * 64,
            rights_status=RightsStatus.PERSONAL_LEARNING,
            source_message_id="tutorial-1",
        )
        session.add(tutorial)
        session.commit()
        tutorial_id = tutorial.id

        recipe = TutorialUnderstandingService().process(session, course.id)
        rules = session.exec(
            select(EditingRule).where(EditingRule.recipe_id == recipe.id).order_by(EditingRule.sort_order)
        ).all()
        stored_recipe = session.exec(select(EditingRecipe)).one()

    assert stored_recipe.version == 1
    assert {rule.category for rule in rules} >= {"hook", "pacing", "captions", "audio", "cta"}
    assert all(rule.source_asset_id == tutorial_id for rule in rules)
    assert all(rule.source_page is not None for rule in rules)
    hook = next(rule for rule in rules if rule.category == "hook")
    assert hook.source_start_ms == 0
    assert hook.source_end_ms == 3000
    assert "使用后的效果" in hook.instruction
    assert stored_recipe.tutorial_asset_id == tutorial_id
    assert stored_recipe.transcript_sha256
    assert hook.evidence_text == hook.instruction
    assert hook.confidence == 1.0


def test_video_tutorial_is_learned_from_routed_asr_with_cited_evidence(tmp_path: Path) -> None:
    tutorial_path = tmp_path / "spoken-tutorial.mp4"
    tutorial_path.write_bytes(b"video-container-only-no-script")
    transcript = TranscriptResult(
        language="zh",
        duration_seconds=8.0,
        provider="fake-asr",
        model="fixture",
        segments=[
            TranscriptSegment(
                text="前三秒先放掉毛问题特写作为钩子",
                start_seconds=0.4,
                end_seconds=3.0,
                confidence=0.96,
            ),
            TranscriptSegment(
                text="结尾给出自然的行动提示",
                start_seconds=5.0,
                end_seconds=7.5,
                confidence=0.91,
            ),
        ],
    )
    transcriber = FakeRoutedTranscriber(transcript)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        course = Course(title="口播教程", source_type="fixture", source_message_id="video-tutorial")
        session.add(course)
        session.commit()
        tutorial = CourseAsset(
            course_id=course.id,
            role=CourseAssetRole.TUTORIAL,
            original_name=tutorial_path.name,
            stored_path=str(tutorial_path),
            mime_type="video/mp4",
            size_bytes=tutorial_path.stat().st_size,
            sha256=hashlib.sha256(tutorial_path.read_bytes()).hexdigest(),
            rights_status=RightsStatus.PERSONAL_LEARNING,
            source_message_id="video-tutorial",
        )
        session.add(tutorial)
        session.commit()
        tutorial_id = tutorial.id

        recipe = TutorialUnderstandingService(transcriber).process(session, course.id)
        rules = list(session.exec(select(EditingRule).where(EditingRule.recipe_id == recipe.id)).all())

    assert transcriber.calls == [(tutorial_path, "production", False)]
    assert recipe.tutorial_asset_id == tutorial_id
    assert recipe.transcript_sha256 == hashlib.sha256(transcript.text.encode("utf-8")).hexdigest()
    assert [(rule.source_start_ms, rule.source_end_ms) for rule in rules] == [(400, 3000), (5000, 7500)]
    assert [rule.evidence_text for rule in rules] == [segment.text for segment in transcript.segments]
    assert [rule.confidence for rule in rules] == [0.96, 0.91]


def test_video_tutorial_distinguishes_operation_example_and_lecture_evidence(tmp_path: Path) -> None:
    tutorial_path = tmp_path / "mixed-tutorial.mp4"
    tutorial_path.write_bytes(b"mixed-tutorial-container")
    transcript = TranscriptResult(
        language="zh",
        duration_seconds=16.0,
        provider="fake-asr",
        model="fixture",
        segments=[
            TranscriptSegment(
                text="先看我的剪映操作，我把素材拖到时间线再点击分割",
                start_seconds=0.0,
                end_seconds=3.0,
                confidence=0.94,
            ),
            TranscriptSegment(
                text="下面播放完成示例",
                start_seconds=4.0,
                end_seconds=6.0,
                confidence=0.95,
            ),
            TranscriptSegment(
                text="这款帽子需要搭配浅色外套，字幕写不要错过，结尾立即下单",
                start_seconds=6.0,
                end_seconds=10.0,
                confidence=0.92,
            ),
            TranscriptSegment(
                text="大家好，欢迎回到课程",
                start_seconds=10.0,
                end_seconds=12.0,
                confidence=0.9,
            ),
            TranscriptSegment(
                text="讲解一下，前三秒先展示佩戴结果作为钩子",
                start_seconds=12.0,
                end_seconds=16.0,
                confidence=0.96,
            ),
        ],
    )
    frames = [
        FrameEvidence(timestamp_seconds=1.5, image_path="operation.jpg", width=1920, height=1080, brightness=90, contrast=40, sharpness=20, ocr_texts=["剪映专业版", "素材", "时间线", "分割"]),
        FrameEvidence(timestamp_seconds=5.0, image_path="example-start.jpg", width=1920, height=1080, brightness=100, contrast=45, sharpness=21, ocr_texts=["成片预览"]),
        FrameEvidence(timestamp_seconds=8.0, image_path="example.jpg", width=1920, height=1080, brightness=110, contrast=50, sharpness=22, ocr_texts=[]),
        FrameEvidence(timestamp_seconds=11.0, image_path="intro.jpg", width=1920, height=1080, brightness=105, contrast=42, sharpness=19, ocr_texts=["课程目录"]),
        FrameEvidence(timestamp_seconds=14.0, image_path="lecture.jpg", width=1920, height=1080, brightness=98, contrast=41, sharpness=18, ocr_texts=["课程讲解"]),
    ]
    analyzer = FakeTutorialMediaAnalyzer(
        MediaAnalysis(
            material_id="tutorial",
            source_path=str(tutorial_path),
            duration_seconds=16.0,
            width=1920,
            height=1080,
            has_audio=True,
            transcript=transcript,
            scenes=[
                SceneInterval(start_seconds=0, end_seconds=4),
                SceneInterval(start_seconds=4, end_seconds=6),
                SceneInterval(start_seconds=6, end_seconds=10),
                SceneInterval(start_seconds=10, end_seconds=12),
                SceneInterval(start_seconds=12, end_seconds=16),
            ],
            frames=frames,
        )
    )
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        course = Course(title="混合教程", source_type="fixture", source_message_id="mixed-video")
        session.add(course)
        session.commit()
        tutorial = CourseAsset(
            course_id=course.id,
            role=CourseAssetRole.TUTORIAL,
            original_name=tutorial_path.name,
            stored_path=str(tutorial_path),
            mime_type="video/mp4",
            size_bytes=tutorial_path.stat().st_size,
            sha256=hashlib.sha256(tutorial_path.read_bytes()).hexdigest(),
            rights_status=RightsStatus.PERSONAL_LEARNING,
            source_message_id="mixed-video",
        )
        session.add(tutorial)
        session.commit()

        recipe = TutorialUnderstandingService(media_analyzer=analyzer).process(session, course.id)
        segments = list(
            session.exec(
                select(TutorialSegment)
                .where(TutorialSegment.recipe_id == recipe.id)
                .order_by(TutorialSegment.sort_order)
            ).all()
        )
        rules = list(session.exec(select(EditingRule).where(EditingRule.recipe_id == recipe.id)).all())

    assert [segment.segment_type for segment in segments] == [
        TutorialSegmentType.SOFTWARE_OPERATION,
        TutorialSegmentType.FINISHED_EXAMPLE,
        TutorialSegmentType.FINISHED_EXAMPLE,
        TutorialSegmentType.INTRO_OUTRO,
        TutorialSegmentType.LECTURE,
    ]
    assert json.loads(segments[0].ocr_text_json) == ["剪映专业版", "素材", "时间线", "分割"]
    assert [rule.category for rule in rules] == ["hook"]
    assert "立即下单" not in " ".join(rule.instruction for rule in rules)
    assert json.loads(segments[1].related_rule_ids_json) == []
    assert json.loads(segments[2].related_rule_ids_json) == []


def test_video_tutorial_rejects_evidence_outside_transcript_duration(tmp_path: Path) -> None:
    tutorial_path = tmp_path / "invalid.mp4"
    tutorial_path.write_bytes(b"invalid-evidence-fixture")
    transcriber = FakeRoutedTranscriber(
        TranscriptResult(
            language="zh",
            duration_seconds=2.0,
            segments=[
                TranscriptSegment(
                    text="前三秒展示结果",
                    start_seconds=0.0,
                    end_seconds=4.0,
                    confidence=0.8,
                )
            ],
        )
    )
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        course = Course(title="越界教程", source_type="fixture", source_message_id="invalid-video")
        session.add(course)
        session.commit()
        session.add(
            CourseAsset(
                course_id=course.id,
                role=CourseAssetRole.TUTORIAL,
                original_name=tutorial_path.name,
                stored_path=str(tutorial_path),
                mime_type="video/mp4",
                size_bytes=tutorial_path.stat().st_size,
                sha256="b" * 64,
                rights_status=RightsStatus.PERSONAL_LEARNING,
                source_message_id="invalid-video",
            )
        )
        session.commit()

        try:
            TutorialUnderstandingService(transcriber).process(session, course.id)
        except ValueError as error:
            assert str(error) == "tutorial_evidence_out_of_bounds"
        else:
            raise AssertionError("out-of-bounds tutorial evidence must fail closed")
