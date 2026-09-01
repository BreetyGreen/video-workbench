from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.models import (
    Course,
    CourseAsset,
    CourseAssetRole,
    CourseProcessingRun,
    EditingRecipe,
    EditingRule,
)


TIME_RANGE = re.compile(r"(?P<start>\d+(?:\.\d+)?)\s*[-—~至]\s*(?P<end>\d+(?:\.\d+)?)\s*秒")


def _category(text: str) -> str:
    if any(token in text for token in ("前三秒", "钩子", "先展示", "结果前置")):
        return "hook"
    if any(token in text for token in ("单镜头", "节奏", "镜头不要超过", "切换")):
        return "pacing"
    if any(token in text for token in ("字幕", "每行", "字体")):
        return "captions"
    if any(token in text for token in ("背景音乐", "旁白", "原声", "噪声", "响度")):
        return "audio"
    if any(token in text for token in ("结尾", "行动提示", "引导", "下单")):
        return "cta"
    if any(token in text for token in ("不要", "禁止", "避免", "不使用")):
        return "negative"
    return "structure"


class TutorialUnderstandingService:
    def __init__(self, transcriber: Any | None = None):
        self.transcriber = transcriber

    def _segments(self, asset: CourseAsset) -> list[tuple[str, int | None, int | None, int]]:
        source = Path(asset.stored_path)
        if asset.mime_type == "text/plain":
            lines = source.read_text(encoding="utf-8-sig").splitlines()
            result = []
            for line_number, line in enumerate(lines, start=1):
                text = line.strip()
                if not text:
                    continue
                match = TIME_RANGE.search(text)
                start_ms = int(float(match.group("start")) * 1000) if match else None
                end_ms = int(float(match.group("end")) * 1000) if match else None
                result.append((text, start_ms, end_ms, line_number))
            return result
        if asset.mime_type.startswith(("video/", "audio/")) and self.transcriber is not None:
            transcript = self.transcriber.transcribe(source)
            return [
                (
                    segment.text.strip(),
                    int(segment.start_seconds * 1000),
                    int(segment.end_seconds * 1000),
                    index,
                )
                for index, segment in enumerate(transcript.segments, start=1)
                if segment.text.strip()
            ]
        return []

    def process(self, session: Session, course_id: str) -> EditingRecipe:
        course = session.get(Course, course_id)
        if course is None:
            raise ValueError("course_not_found")
        tutorials = list(
            session.exec(
                select(CourseAsset)
                .where(CourseAsset.course_id == course_id)
                .where(CourseAsset.role == CourseAssetRole.TUTORIAL)
                .order_by(CourseAsset.created_at, CourseAsset.id)
            ).all()
        )
        if not tutorials:
            raise ValueError("course_tutorial_required")

        run = CourseProcessingRun(course_id=course_id, state="processing")
        course.status = "processing"
        session.add_all([run, course])
        session.commit()
        try:
            existing = session.exec(
                select(EditingRecipe)
                .where(EditingRecipe.course_id == course_id)
                .order_by(EditingRecipe.version.desc())
            ).first()
            recipe = EditingRecipe(
                course_id=course_id,
                version=(existing.version + 1) if existing else 1,
                title=f"{course.title}剪辑规则",
                summary="从课程教程中提取的、带原文位置引用的剪辑规则",
            )
            session.add(recipe)
            session.commit()
            order = 0
            for tutorial in tutorials:
                for text, start_ms, end_ms, source_page in self._segments(tutorial):
                    order += 1
                    session.add(
                        EditingRule(
                            recipe_id=recipe.id,
                            category=_category(text),
                            instruction=text,
                            source_asset_id=tutorial.id,
                            source_start_ms=start_ms,
                            source_end_ms=end_ms,
                            source_page=source_page,
                            sort_order=order,
                        )
                    )
            if order == 0:
                raise ValueError("tutorial_text_not_extracted")
            run.state = "completed"
            run.finished_at = datetime.now(UTC)
            course.status = "processed"
            course.updated_at = datetime.now(UTC)
            session.add_all([run, course])
            session.commit()
            session.refresh(recipe)
            return recipe
        except Exception as error:
            session.rollback()
            run.state = "failed"
            run.error_code = str(error)
            run.finished_at = datetime.now(UTC)
            course.status = "failed"
            session.add_all([run, course])
            session.commit()
            raise
