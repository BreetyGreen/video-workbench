from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.adapters.dify import WorkflowUsage
from app.config import Settings
from app.models import Course, CourseAsset, CourseAssetRole, EditingRule, RightsStatus, TutorialSegment
from app.schemas.editing import TranscriptResult, TranscriptSegment
from app.schemas.tutorial_study import LessonStudy, StudyChunkReply
from app.services.tutorial_understanding_service import TutorialUnderstandingService
from app.services.tutorial_video_study_service import TutorialVideoStudyService

CHUNK_REPLY = {
    "segments": [
        {"start": 0.0, "end": 0.6, "type": "lecture", "summary": "老师说先剪气口",
         "teacher_actions": [],
         "rules": [{"category": "Audio", "instruction": "先剪掉气口再配镜头", "evidence_quote": "先把气口剪掉", "start": 0.1, "end": 0.5}]},
        {"start": 0.6, "end": 1.0, "type": "software_operation", "summary": "点击分割按钮",
         "teacher_actions": ["点击底部工具栏分割"],
         "rules": [{"category": "nonsense", "instruction": "分割后删除无声段", "evidence_quote": "删掉", "start": 5.0, "end": 9.0}]},
    ],
    "uncertain": ["工具栏文字模糊"],
}


class FakeDirector:
    def __init__(self, replies=None, fail_indexes=()):
        self.configured = True
        self.model = "qwen3-vl-plus"
        self.calls: list[dict] = []
        self.replies = replies
        self.fail_indexes = set(fail_indexes)

    def complete_json(self, parts, *, max_tokens=None, model=None, system=None):
        index = len(self.calls)
        self.calls.append({"parts": parts, "max_tokens": max_tokens, "model": model})
        if index in self.fail_indexes:
            raise RuntimeError("boom")
        video = parts[0]
        assert video["type"] == "video_url" and video["video_url"]["url"].startswith("data:video/mp4;base64,")
        assert video["fps"] == 0.5
        assert "转写" in parts[1]["text"]
        return (self.replies[index] if self.replies else CHUNK_REPLY), WorkflowUsage("req", 100, 20, 120)


def transcript(duration: float) -> TranscriptResult:
    return TranscriptResult(duration_seconds=duration, provider="volcano_bigasr", segments=[
        TranscriptSegment(text="先把气口剪掉。", start_seconds=0.1, end_seconds=0.5),
        TranscriptSegment(text="然后删掉。", start_seconds=1.1, end_seconds=1.5),
    ])


def settings(tmp_path: Path, **overrides) -> Settings:
    values = {"data_dir": tmp_path / "data", "tutorial_study_chunk_seconds": 20, "tutorial_study_concurrency": 2}
    values.update(overrides)
    return Settings(**values)


def test_plan_chunks_cover_duration(tmp_path: Path):
    service = TutorialVideoStudyService(settings(tmp_path, tutorial_study_chunk_seconds=120), FakeDirector())
    plans = service.plan(300)
    assert [(p.start_seconds, p.end_seconds) for p in plans] == [(0, 120), (120, 240), (240, 300)]
    assert service.plan(0.2) == []


def test_study_absolute_times_categories_resume_and_failures(tmp_path: Path, ffmpeg_fixture: Path, monkeypatch):
    director = FakeDirector(fail_indexes={1})
    # Single worker keeps call order deterministic so "the second call fails" means chunk 1.
    service = TutorialVideoStudyService(settings(tmp_path, tutorial_study_concurrency=1), director)
    # 2 s fixture -> force two chunks by pretending the lesson is 40 s and shrinking chunks to 20 s
    work = tmp_path / "study"
    lesson = service.study(ffmpeg_fixture, transcript(40), work, duration_seconds=40)

    assert lesson.chunk_count == 2 and lesson.completed_chunks == 1
    assert lesson.failed_chunks[0]["index"] == 1 and "boom" in lesson.failed_chunks[0]["error"]
    assert not lesson.complete
    assert [s.type for s in lesson.segments] == ["lecture", "software_operation"]
    assert lesson.segments[1].teacher_actions == ["点击底部工具栏分割"]
    assert [r.category for r in lesson.rules] == ["audio", "structure"]
    assert (lesson.rules[0].start_ms, lesson.rules[0].end_ms) == (100, 500)
    # out-of-chunk rule times are clamped into the chunk window (chunk 0 = 0-20 s)
    assert (lesson.rules[1].start_ms, lesson.rules[1].end_ms) == (5000, 9000)
    assert lesson.usage == {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120, "calls": 1}
    assert lesson.uncertain == ["工具栏文字模糊"]
    assert (work / "chunk-0000.json").is_file() and (work / "lesson-study.json").is_file()
    assert not list(work.glob("*.mp4"))  # transcoded chunks are removed after use

    # Second run resumes: chunk 0 is cached, only the failed chunk is retried.
    director.fail_indexes = set()
    calls_before = len(director.calls)
    second = service.study(ffmpeg_fixture, transcript(40), work, duration_seconds=40)
    assert len(director.calls) == calls_before + 1
    assert second.complete and second.completed_chunks == 2
    assert second.usage["calls"] == 2


def test_unconfigured_study_is_refused(tmp_path: Path, ffmpeg_fixture: Path):
    service = TutorialVideoStudyService(settings(tmp_path), SimpleNamespace(configured=False, model="x"))
    assert service.configured is False
    with pytest.raises(RuntimeError, match="tutorial_study_not_configured"):
        service.study(ffmpeg_fixture, transcript(2), tmp_path / "s")


class FakeStudy:
    def __init__(self, lesson: LessonStudy | None = None, *, error: Exception | None = None):
        self.configured = True
        self.lesson = lesson
        self.error = error
        self.calls: list[tuple[Path, Path]] = []

    def study(self, source, transcript, work_dir, *, duration_seconds=None):
        self.calls.append((source, work_dir))
        if self.error:
            raise self.error
        return self.lesson


class FakeTranscriber:
    def __init__(self, result):
        self.result = result

    def transcribe(self, source, *, quality_profile, cloud_processing_allowed):
        return self.result


def _course_with_video(session: Session, root: Path) -> tuple[Course, CourseAsset]:
    source = root / "courses" / "c1" / "assets" / "lesson.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"video")
    course = Course(title="剪辑课", source_message_id="study-1")
    session.add(course)
    session.commit()
    asset = CourseAsset(course_id=course.id, role=CourseAssetRole.TUTORIAL, original_name="lesson.mp4",
                        stored_path=str(source), mime_type="video/mp4", size_bytes=5, sha256="a" * 64,
                        rights_status=RightsStatus.PERSONAL_LEARNING)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return course, asset


def _lesson() -> LessonStudy:
    return LessonStudy(source_name="lesson.mp4", duration_seconds=40, model="qwen3-vl-plus", fps=0.5, chunk_seconds=20,
                       chunk_count=2, completed_chunks=2, segments=[
                           {"start_ms": 0, "end_ms": 600, "type": "lecture", "summary": "先剪气口", "teacher_actions": [], "chunk_index": 0},
                           {"start_ms": 600, "end_ms": 1000, "type": "software_operation", "summary": "点分割",
                            "teacher_actions": ["点击分割"], "chunk_index": 0}],
                       rules=[{"category": "audio", "instruction": "先剪掉气口再配镜头", "evidence_quote": "先把气口剪掉",
                               "start_ms": 100, "end_ms": 500, "chunk_index": 0}],
                       uncertain=["工具栏模糊"], usage={"total_tokens": 120})


def test_understanding_uses_vision_study_rules_with_model_categories(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    SQLModel.metadata.create_all(engine)
    study = FakeStudy(_lesson())
    service = TutorialUnderstandingService(FakeTranscriber(transcript(40)), study=study)
    with Session(engine) as session:
        course, asset = _course_with_video(session, tmp_path)
        stored_path = Path(asset.stored_path)
        recipe = service.process(session, course.id, cloud_processing_allowed=True)
        rules = session.exec(select(EditingRule).where(EditingRule.recipe_id == recipe.id)).all()
        segments = session.exec(select(TutorialSegment).where(TutorialSegment.recipe_id == recipe.id)
                                .order_by(TutorialSegment.sort_order)).all()
        rule_rows = [(r.category, r.instruction, r.source_start_ms, r.source_end_ms) for r in rules]
        segment_types = [s.segment_type.value for s in segments]
        cues = [s.visual_cues_json for s in segments]

    assert len(study.calls) == 1
    assert rule_rows == [("audio", "先剪掉气口再配镜头", 100, 500)]
    assert segment_types == ["lecture", "lecture", "software_operation"]
    assert any("action:点击分割" in cue for cue in cues)
    assert stored_path.with_suffix(".lesson-study.json").is_file()


def test_understanding_falls_back_to_local_heuristics_when_study_fails_or_is_off(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    SQLModel.metadata.create_all(engine)
    failing = FakeStudy(error=RuntimeError("quota"))
    service = TutorialUnderstandingService(FakeTranscriber(transcript(40)), study=failing)
    with Session(engine) as session:
        course, asset = _course_with_video(session, tmp_path)
        stored_path, asset_id = Path(asset.stored_path), asset.id
        recipe = service.process(session, course.id, cloud_processing_allowed=True)
        rules = session.exec(select(EditingRule).where(EditingRule.recipe_id == recipe.id)).all()
        categories = [r.category for r in rules]
    assert len(failing.calls) == 1
    assert categories and all(categories)
    error = json.loads((stored_path.parent / "analysis" / "tutorial-study" / asset_id / "study-error.json").read_text(encoding="utf-8"))
    assert error["error_type"] == "RuntimeError"

    # Without cloud consent the study is never called.
    consentless = FakeStudy(_lesson())
    service = TutorialUnderstandingService(FakeTranscriber(transcript(40)), study=consentless)
    with Session(engine) as session:
        course2 = Course(title="剪辑课2", source_message_id="study-2")
        session.add(course2)
        session.commit()
        source = tmp_path / "courses" / "c2" / "assets" / "lesson.mp4"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"video")
        session.add(CourseAsset(course_id=course2.id, role=CourseAssetRole.TUTORIAL, original_name="lesson.mp4",
                                stored_path=str(source), mime_type="video/mp4", size_bytes=5, sha256="b" * 64,
                                rights_status=RightsStatus.PERSONAL_LEARNING))
        session.commit()
        service.process(session, course2.id, cloud_processing_allowed=False)
    assert consentless.calls == []


def test_chunk_reply_tolerates_unknown_fields_and_types():
    parsed = StudyChunkReply.model_validate({"segments": [{"start": 0, "end": 1, "type": "Weird", "summary": "x",
                                                            "rules": [{"category": "hook", "instruction": "y", "start": 0, "end": 1, "extra": 1}]}],
                                             "uncertain": "not-a-list", "extra": True})
    assert parsed.segments[0].type == "other"
    assert parsed.segments[0].rules[0].category == "hook"
    assert parsed.uncertain == []


def test_study_rows_never_collide_on_identical_spans_and_sidecar_is_reused(tmp_path: Path):
    from app.schemas.editing import MediaAnalysis

    engine = create_engine(f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    SQLModel.metadata.create_all(engine)
    lesson = _lesson()
    # A rule quoted over exactly its parent segment's span, twice.
    from app.schemas.tutorial_study import LessonStudyRule
    lesson.rules = [LessonStudyRule(category="audio", instruction="先剪气口", evidence_quote="q", start_ms=0, end_ms=600, chunk_index=0),
                    LessonStudyRule(category="pacing", instruction="再配镜头", evidence_quote="q", start_ms=0, end_ms=600, chunk_index=0)]
    study = FakeStudy(lesson)

    class CountingAnalyzer:
        def __init__(self):
            self.calls = 0

        def analyze(self, source, *, material_id, output_dir, quality_profile, cloud_processing_allowed):
            self.calls += 1
            return MediaAnalysis(material_id=material_id, source_path=str(source), duration_seconds=40, width=720,
                                 height=1280, has_audio=True, transcript=transcript(40))

    analyzer = CountingAnalyzer()
    service = TutorialUnderstandingService(FakeTranscriber(transcript(40)), media_analyzer=analyzer, study=study)
    with Session(engine) as session:
        course, asset = _course_with_video(session, tmp_path)
        recipe = service.process(session, course.id, cloud_processing_allowed=True)
        spans = sorted((s.source_asset_id, s.start_ms, s.end_ms) for s in
                       session.exec(select(TutorialSegment).where(TutorialSegment.recipe_id == recipe.id)).all())
        assert len(spans) == len(set(spans)) == 4  # 2 summaries + 2 rules, all distinct spans
        rules = session.exec(select(EditingRule).where(EditingRule.recipe_id == recipe.id)).all()
        assert sorted(r.category for r in rules) == ["audio", "pacing"]
        # Second processing run reuses the analysis sidecar instead of re-transcribing.
        service.process(session, course.id, cloud_processing_allowed=True)
    assert analyzer.calls == 1
