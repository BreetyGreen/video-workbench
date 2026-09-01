from __future__ import annotations

from pathlib import Path
import hashlib

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    Course,
    CourseAsset,
    CourseAssetRole,
    EditingRecipe,
    EditingRule,
    RightsStatus,
)
from app.services.tutorial_understanding_service import TutorialUnderstandingService
from app.schemas.editing import TranscriptResult, TranscriptSegment


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
