from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    Course,
    CourseProcessingRun,
    EditingRecipe,
    EditingRule,
    MaterialShot,
)


def test_recipe_rules_and_material_shots_round_trip() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        course = Course(title="course", source_type="fixture", source_message_id="m-knowledge")
        session.add(course)
        session.commit()
        recipe = EditingRecipe(course_id=course.id, version=1, title="20 秒宠物商品剪辑法", summary="结果前置")
        session.add(recipe)
        session.commit()
        rule = EditingRule(
            recipe_id=recipe.id,
            category="hook",
            instruction="前三秒先展示使用后的效果",
            source_asset_id="asset-tutorial",
            source_start_ms=0,
            source_end_ms=3000,
            sort_order=1,
        )
        shot = MaterialShot(
            asset_id="asset-material",
            start_ms=0,
            end_ms=2500,
            thumbnail_path="thumbs/shot-1.jpg",
            ocr_text="柔软透气",
            tags_json='["pet","product","close_up"]',
            embedding_json="[0.1,0.2]",
            phash="0f0f0f0f0f0f0f0f",
        )
        run = CourseProcessingRun(course_id=course.id, state="completed")
        session.add_all([rule, shot, run])
        session.commit()

        stored_rule = session.exec(select(EditingRule)).one()
        stored_shot = session.exec(select(MaterialShot)).one()
        stored_run = session.exec(select(CourseProcessingRun)).one()

    assert stored_rule.source_start_ms == 0
    assert stored_rule.source_end_ms == 3000
    assert stored_shot.end_ms > stored_shot.start_ms
    assert stored_shot.phash == "0f0f0f0f0f0f0f0f"
    assert stored_run.state == "completed"
