from __future__ import annotations

from pathlib import Path

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
