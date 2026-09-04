from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.config import Settings
from app.models import Course, CourseAsset, CourseAssetRole, RightsStatus
from app.services.course_material_analysis_service import CourseMaterialAnalysisService


def test_video_material_is_split_into_persisted_shots(
    tmp_path: Path,
    ffmpeg_fixture: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url="sqlite://",
        ffmpeg_bin=ffmpeg_bin,
        ffprobe_bin=ffprobe_bin,
        ocr_enabled=False,
    )
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        course = Course(title="course", source_type="fixture", source_message_id="shots-1")
        session.add(course)
        session.commit()
        asset = CourseAsset(
            course_id=course.id,
            role=CourseAssetRole.MATERIAL,
            original_name="pet-product.mp4",
            stored_path=str(ffmpeg_fixture),
            mime_type="video/mp4",
            size_bytes=ffmpeg_fixture.stat().st_size,
            sha256="f" * 64,
            rights_status=RightsStatus.COMMERCIAL_AUTHORIZED,
            source_message_id="shots-1",
        )
        session.add(asset)
        session.commit()

        shots = CourseMaterialAnalysisService(settings).analyze_asset(session, asset.id)

    assert shots
    assert shots[0].start_ms == 0
    assert shots[-1].end_ms <= 2000
    assert all(shot.end_ms > shot.start_ms for shot in shots)
    assert all(Path(shot.thumbnail_path).is_file() for shot in shots)
    assert all(len(shot.phash) == 16 for shot in shots)
    tags = json.loads(shots[0].tags_json)
    assert "landscape" in tags
    assert "has_audio" in tags
