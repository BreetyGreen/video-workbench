from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Course, CourseAsset, CourseAssetRole, RightsStatus


def test_course_assets_round_trip_roles_and_rights(tmp_path: Path) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        course = Course(
            title="宠物短视频剪辑课",
            source_type="dingtalk",
            source_user="staff-1",
            source_conversation="group-1",
            source_message_id="message-1",
        )
        session.add(course)
        session.commit()
        session.refresh(course)

        assets = [
            CourseAsset(
                course_id=course.id,
                role=CourseAssetRole.TUTORIAL,
                original_name="tutorial.mp4",
                stored_path=str(tmp_path / "tutorial.mp4"),
                mime_type="video/mp4",
                size_bytes=10,
                sha256="a" * 64,
                rights_status=RightsStatus.PERSONAL_LEARNING,
                source_message_id="message-1",
            ),
            CourseAsset(
                course_id=course.id,
                role=CourseAssetRole.REFERENCE,
                original_name="reference.mp4",
                stored_path=str(tmp_path / "reference.mp4"),
                mime_type="video/mp4",
                size_bytes=11,
                sha256="b" * 64,
                rights_status=RightsStatus.PERSONAL_LEARNING,
                source_message_id="message-1",
            ),
            CourseAsset(
                course_id=course.id,
                role=CourseAssetRole.MATERIAL,
                original_name="material.mp4",
                stored_path=str(tmp_path / "material.mp4"),
                mime_type="video/mp4",
                size_bytes=12,
                sha256="c" * 64,
                rights_status=RightsStatus.COMMERCIAL_AUTHORIZED,
                source_message_id="message-1",
            ),
        ]
        session.add_all(assets)
        session.commit()

        stored = session.exec(
            select(CourseAsset).where(CourseAsset.course_id == course.id).order_by(CourseAsset.original_name)
        ).all()

    assert [asset.role for asset in stored] == [
        CourseAssetRole.MATERIAL,
        CourseAssetRole.REFERENCE,
        CourseAssetRole.TUTORIAL,
    ]
    assert stored[0].rights_status == RightsStatus.COMMERCIAL_AUTHORIZED


def test_course_source_message_is_unique() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(Course(title="A", source_type="dingtalk", source_message_id="message-1"))
        session.commit()
        session.add(Course(title="B", source_type="dingtalk", source_message_id="message-1"))

        with pytest.raises(IntegrityError):
            session.commit()


def test_duplicate_asset_role_and_hash_is_rejected(tmp_path: Path) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        course = Course(title="A", source_type="fixture", source_message_id="fixture-1")
        session.add(course)
        session.commit()
        for name in ("one.mp4", "two.mp4"):
            session.add(
                CourseAsset(
                    course_id=course.id,
                    role=CourseAssetRole.MATERIAL,
                    original_name=name,
                    stored_path=str(tmp_path / name),
                    mime_type="video/mp4",
                    size_bytes=5,
                    sha256="d" * 64,
                    rights_status=RightsStatus.UNKNOWN,
                    source_message_id="fixture-1",
                )
            )
            if name == "one.mp4":
                session.commit()

        with pytest.raises(IntegrityError):
            session.commit()
