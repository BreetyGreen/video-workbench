"""Persist tutorial provenance for ordinary course jobs, not only built-in demos."""
import json
from pathlib import Path
import shutil

from sqlmodel import select

from app.models import CourseAsset, TutorialSegment


def bounded_strings(raw):
    try:
        values = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    return [v for v in values[:200] if isinstance(v, str) and len(v) <= 2000] if isinstance(values, list) else []


def write_course_evidence(session, settings, task_id, recipe, rules):
    # Task creation commits expire SQLAlchemy rows; model_dump alone would then
    # serialize empty dictionaries instead of loading the course evidence.
    session.refresh(recipe)
    for rule in rules:
        session.refresh(rule)
    target = settings.artifact_dir / task_id
    target.mkdir(parents=True, exist_ok=True)
    segments = session.exec(select(TutorialSegment).where(TutorialSegment.recipe_id == recipe.id)
                            .order_by(TutorialSegment.sort_order)).all()
    payloads = [{"id": s.id, "source_asset_id": s.source_asset_id, "segment_type": s.segment_type.value,
                 "start_ms": s.start_ms, "end_ms": s.end_ms, "source_page": s.source_page,
                 "transcript_text": s.transcript_text, "confidence": s.confidence, "sort_order": s.sort_order,
                 "ocr_texts": bounded_strings(s.ocr_text_json), "visual_cues": bounded_strings(s.visual_cues_json),
                 "related_rule_ids": bounded_strings(s.related_rule_ids_json)} for s in segments]
    (target / "tutorial-segments.json").write_text(json.dumps({"recipe_id": recipe.id, "segments": payloads}, ensure_ascii=False), encoding="utf-8")
    (target / "learned-course-recipe.json").write_text(json.dumps({
        "recipe": recipe.model_dump(mode="json"), "rules": [r.model_dump(mode="json") for r in rules],
        "segments": payloads}, ensure_ascii=False), encoding="utf-8")
    tutorial = session.get(CourseAsset, recipe.tutorial_asset_id) if recipe.tutorial_asset_id else None
    if tutorial is None:
        return
    source = Path(tutorial.stored_path).resolve()
    if (settings.data_dir / "courses").resolve() not in source.parents:
        raise ValueError("tutorial_evidence_path_outside_storage")
    for suffix, name in [(".transcript.json", "tutorial-transcript.json"),
                         (".tutorial-analysis.json", "tutorial-visual-analysis.json")]:
        candidate = source.with_suffix(suffix)
        if candidate.is_file():
            shutil.copy2(candidate, target / name)
