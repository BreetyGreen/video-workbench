import json
import math
from pathlib import Path

from PIL import Image
from sqlmodel import select

from app.models import CourseAsset, CourseAssetRole, EditingRecipe
from app.schemas.director import DirectorPlan
from app.schemas.editing import MediaAnalysis


def validate_director_sources(plan: DirectorPlan, analyses: list[MediaAnalysis]) -> None:
    """Validate mechanical provenance, NOT the truth of model-written narration."""
    by_id = {item.material_id: item for item in analyses}
    intervals: dict[str, list[tuple[float, float]]] = {}
    for beat in plan.beats:
        source = by_id.get(beat.material_id)
        if source is None:
            raise ValueError('director_unknown_material')
        if beat.source_end_seconds > source.duration_seconds:
            raise ValueError('director_source_out_of_bounds')
        for start, end in intervals.setdefault(beat.material_id, []):
            if min(end, beat.source_end_seconds) - max(start, beat.source_start_seconds) > .02:
                raise ValueError('director_source_overlap')
        intervals[beat.material_id].append((beat.source_start_seconds, beat.source_end_seconds))


def narration_violations(plan: DirectorPlan, terms: list[str]) -> list[tuple[int, str, str]]:
    """(beat number, term, narration) for every beat whose narration contains a prohibited term."""
    found = []
    for index, beat in enumerate(plan.beats, start=1):
        for term in terms:
            if term and term in beat.narration:
                found.append((index, term, beat.narration))
    return found


def repair_director_plan(plan: DirectorPlan, analyses: list[MediaAnalysis], *,
                         aliases: dict[str, str] | None = None) -> tuple[DirectorPlan, list[str]]:
    """Mechanically repair a model plan before validation; never invent beats.

    - material_id given as a file name / alias or an unambiguous id prefix is mapped to the real id
    - source_end_seconds beyond the material is clamped (dropped if the beat becomes shorter than 0.3 s)
    - a beat overlapping an earlier beat of the same material is dropped
    - bookends are restored on what remains; fewer than two beats raises
    Every change is returned as a human-readable note.
    """
    by_id = {item.material_id: item for item in analyses}
    alias_map = {str(key): value for key, value in (aliases or {}).items() if value in by_id}
    notes: list[str] = []
    kept = []
    intervals: dict[str, list[tuple[float, float]]] = {}
    for index, beat in enumerate(plan.beats, start=1):
        material_id = beat.material_id
        if material_id not in by_id:
            resolved = alias_map.get(material_id)
            if resolved is None:
                prefix = [item for item in by_id if len(material_id) >= 8 and item.startswith(material_id)]
                resolved = prefix[0] if len(prefix) == 1 else None
            if resolved is None:
                notes.append(f"beat {index}: unknown material '{material_id[:60]}' dropped")
                continue
            notes.append(f"beat {index}: material '{material_id[:60]}' mapped to {resolved}")
            material_id = resolved
        source = by_id[material_id]
        start, end = beat.source_start_seconds, beat.source_end_seconds
        if end > source.duration_seconds + 1e-6:
            end = source.duration_seconds
            notes.append(f"beat {index}: end clamped to {end:.2f}s")
        if end - start < 0.3:
            notes.append(f"beat {index}: dropped, shorter than 0.3s after clamping")
            continue
        if any(min(existing_end, end) - max(existing_start, start) > 0.02
               for existing_start, existing_end in intervals.get(material_id, [])):
            notes.append(f"beat {index}: dropped, overlaps an earlier beat of {material_id}")
            continue
        intervals.setdefault(material_id, []).append((start, end))
        kept.append(beat.model_copy(update={"material_id": material_id, "source_end_seconds": end}))
    if len(kept) < 2:
        raise ValueError('director_plan_unrepairable')
    for position, beat in enumerate(kept):
        wanted = 'hook' if position == 0 else 'closing' if position == len(kept) - 1 else None
        if wanted and beat.purpose != wanted:
            notes.append(f"beat purpose reset to {wanted} at position {position + 1}")
            kept[position] = beat.model_copy(update={"purpose": wanted})
        elif wanted is None and beat.purpose in {'hook', 'closing'}:
            kept[position] = beat.model_copy(update={"purpose": 'identity' if beat.purpose == 'hook' else 'usage'})
    repaired = DirectorPlan(version=1, beats=kept)
    validate_director_sources(repaired, analyses)
    return repaired, notes


def material_catalog(analyses: list[MediaAnalysis]) -> list[dict]:
    """Bounded evidence only. Never send local source paths to the model."""
    catalog = []
    for item in analyses[:20]:
        entry = dict(material_id=item.material_id, duration_seconds=item.duration_seconds,
                 scenes=[dict(start_seconds=s.start_seconds, end_seconds=s.end_seconds)
                         for s in item.scenes[:20]],
                 transcript=item.transcript.text[:600],
                 ocr=[dict(timestamp_seconds=f.timestamp_seconds, texts=[t[:80] for t in f.ocr_texts[:3]])
                      for f in item.frames[:4]],
                 evidence_mode='transcript_ocr_only_not_visual_understanding')
        if len(json.dumps(catalog + [entry], ensure_ascii=False)) > 36000:
            break
        catalog.append(entry)
    return catalog


def visual_frame_inputs(analyses: list[MediaAnalysis], analysis_root: Path) -> tuple[list[Path], list[dict]]:
    """Sample task-owned frames, not full-video understanding or verified facts."""
    root = analysis_root.resolve()
    candidates = []
    for item in analyses[:20]:
        frames = sorted((f for f in item.frames if math.isfinite(f.timestamp_seconds)
                         and 0 <= f.timestamp_seconds < item.duration_seconds),
                        key=lambda f: f.timestamp_seconds)
        candidates.append((item, [frames[0], frames[-1]] if frames else []))
    paths, manifest = [], []
    seen = set()
    # Round-robin prevents a long first video consuming the whole visual budget.
    for index in range(2):
        for item, frames in candidates:
            if index >= len(frames):
                continue
            frame = frames[index]
            try:
                path = Path(frame.image_path).resolve(strict=True)
                if path in seen or not path.is_relative_to(root) or not path.is_file():
                    continue
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
                with Image.open(path) as image:
                    if image.format not in {'JPEG', 'PNG'} or max(image.size) > 4096:
                        continue
                    image.load()
            except (OSError, ValueError, Image.DecompressionBombError):
                continue
            seen.add(path)
            paths.append(path)
            manifest.append(dict(image_index=len(paths), material_id=item.material_id,
                                 timestamp_seconds=frame.timestamp_seconds))
            if len(paths) == 8:
                return paths, manifest
    return paths, manifest


def role_visual_frame_inputs(analyses: list[MediaAnalysis], analysis_root: Path, *,
                             reference: MediaAnalysis | None = None,
                             tutorials: list[MediaAnalysis] | None = None,
                             tutorial_root: Path | None = None) -> tuple[list[Path], list[dict]]:
    """Reserve role-labelled evidence without admitting it to the editable catalog."""
    ref_paths, ref_manifest = visual_frame_inputs([reference], analysis_root) if reference else ([], [])
    tutorial_paths, tutorial_manifest = visual_frame_inputs(
        (tutorials or [])[:2], tutorial_root if tutorial_root is not None else analysis_root)
    tutorial_paths, tutorial_manifest = tutorial_paths[:2], tutorial_manifest[:2]
    paths, manifest = visual_frame_inputs(analyses, analysis_root)
    budget = 8 - len(ref_paths) - len(tutorial_paths)
    paths = paths[:budget] + ref_paths + tutorial_paths
    manifest = [dict(item, role='editable_material') for item in manifest[:budget]] + [
        dict(item, role='reference_not_editable') for item in ref_manifest] + [
        dict(item, role='tutorial_not_editable') for item in tutorial_manifest]
    return paths, [dict(item, image_index=index) for index, item in enumerate(manifest, 1)]


def load_course_tutorial_analyses(session, recipe_id, data_root: Path) -> list[MediaAnalysis]:
    """Read at most two owned tutorial sidecars; image validation happens on sampling.

    This does not copy files or treat a recorded analysis as semantic verification.
    The database relationship supplies the course and role, never caller paths.
    """
    if session is None or not recipe_id:
        return []
    recipe = session.get(EditingRecipe, recipe_id)
    if recipe is None:
        return []
    assets = session.exec(select(CourseAsset)
        .where(CourseAsset.course_id == recipe.course_id)
        .where(CourseAsset.role == CourseAssetRole.TUTORIAL)
        .where(CourseAsset.mime_type.startswith('video/'))
        .order_by(CourseAsset.created_at, CourseAsset.id).limit(2)).all()
    root = data_root.resolve()
    analyses = []
    for asset in assets:
        try:
            source = Path(asset.stored_path).resolve()
            if not source.is_relative_to(root):
                continue
            sidecar = source.with_suffix('.tutorial-analysis.json').resolve(strict=True)
            if not sidecar.is_relative_to(root) or not sidecar.is_file():
                continue
            with sidecar.open('rb') as stream:
                payload = stream.read(4 * 1024 * 1024 + 1)
            if len(payload) > 4 * 1024 * 1024:
                continue
            analysis = MediaAnalysis.model_validate_json(payload)
            if analysis.material_id == asset.id:
                analyses.append(analysis)
        except (OSError, ValueError):
            continue
    return analyses
