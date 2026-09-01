from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine

from app.models import Course, CourseAsset, CourseAssetRole, MaterialShot, RightsStatus
from app.services.course_material_search_service import CourseMaterialSearchService


def test_search_ranks_text_and_filters_commercial_rights() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        course = Course(title="course", source_type="fixture", source_message_id="search-1")
        session.add(course)
        session.commit()
        authorized = CourseAsset(
            course_id=course.id, role=CourseAssetRole.MATERIAL, original_name="宠物帽子特写.mp4",
            stored_path="authorized.mp4", mime_type="video/mp4", size_bytes=1, sha256="a" * 64,
            rights_status=RightsStatus.COMMERCIAL_AUTHORIZED, source_message_id="search-1",
        )
        learning = CourseAsset(
            course_id=course.id, role=CourseAssetRole.MATERIAL, original_name="帽子教程.mp4",
            stored_path="learning.mp4", mime_type="video/mp4", size_bytes=1, sha256="b" * 64,
            rights_status=RightsStatus.PERSONAL_LEARNING, source_message_id="search-1",
        )
        session.add_all([authorized, learning])
        session.commit()
        session.add_all([
            MaterialShot(asset_id=authorized.id, start_ms=0, end_ms=2000, ocr_text="防晒宠物帽", tags_json='["pet","hat","close_up"]', phash="0000000000000000"),
            MaterialShot(asset_id=learning.id, start_ms=0, end_ms=2000, ocr_text="宠物帽子教程", tags_json='["pet","hat"]', phash="0000000000000001"),
        ])
        session.commit()

        all_results = CourseMaterialSearchService().search(session, course.id, "宠物 帽子", commercial=False)
        commercial = CourseMaterialSearchService().search(session, course.id, "宠物 帽子", commercial=True)

    assert len(all_results) == 2
    assert len(commercial) == 1
    assert commercial[0].rights_status == "commercial_authorized"
    assert commercial[0].combined_score > 0
