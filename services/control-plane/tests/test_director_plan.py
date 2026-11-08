from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.analysis import EditRecipe
from app.schemas.editing import MediaAnalysis, SceneInterval
from app.services.pipeline_service import PipelineService
from app.services.timeline_service import TimelinePlanner


def recipe_payload():
    return dict(hook_rules=['展示主体'], target_duration_seconds=6,
                pacing=[dict(from_second=0, to_second=6, instruction='按语义切镜')],
                track_layout=['video'], caption_style='白字', audio_rules=[],
                prohibited_elements=[], qa_thresholds=dict(max_silence_seconds=1, max_black_seconds=.1),
                director_plan=dict(version=1, beats=[
                    dict(purpose='hook', narration='绿豆沙倒进冰杯。', material_id='drink',
                         source_start_seconds=4, source_end_seconds=7, rationale='展示液体'),
                    dict(purpose='closing', narration='看看包装再选择。', material_id='drink',
                         source_start_seconds=0, source_end_seconds=3, rationale='展示包装')]))


def media():
    return [MediaAnalysis(material_id='drink', source_path='drink.mp4', duration_seconds=10,
                          width=1080, height=1920, has_audio=False,
                          scenes=[SceneInterval(start_seconds=0, end_seconds=10)])]


def test_director_narration_is_not_replaced_by_pet_template():
    recipe = EditRecipe.model_validate(recipe_payload())
    task = SimpleNamespace(title='绿豆沙', content_type='商品介绍', requirements_text='', tutorial_text='')
    assert PipelineService._narration_text(task, target_seconds=6, recipe=recipe) == '绿豆沙倒进冰杯。看看包装再选择。'


def test_director_preserves_all_beats_when_duration_shrinks():
    timeline = TimelinePlanner().plan(media(), title='绿豆沙', target_seconds=4,
                                      recipe=EditRecipe.model_validate(recipe_payload()))
    assert [clip.source_start_seconds for clip in timeline.clips] == [4, 0]
    assert [clip.duration_seconds for clip in timeline.clips] == [2, 2]
    assert timeline.actual_duration_seconds == 4
    assert timeline.engine == 'director_plan'


def test_director_can_use_validated_intervals_without_legacy_scene_candidates():
    sources = media()
    sources[0].scenes = []
    timeline = TimelinePlanner().plan(sources, title='饮品', recipe=EditRecipe.model_validate(recipe_payload()))
    assert [clip.source_start_seconds for clip in timeline.clips] == [4, 0]


def test_director_minimum_duration_does_not_drop_closing_due_to_float_rounding():
    timeline = TimelinePlanner().plan(media(), title='饮品', target_seconds=.6,
                                      recipe=EditRecipe.model_validate(recipe_payload()))
    assert len(timeline.clips) == 2


@pytest.mark.parametrize('count', [3, 7, 20, 40])
def test_all_director_beats_survive_minimum_scaled_duration(count):
    payload = recipe_payload()
    payload['target_duration_seconds'] = 60
    payload['director_plan']['beats'] = [dict(
        purpose='hook' if i == 0 else 'closing' if i == count - 1 else 'feature',
        narration='完整句子。', material_id='drink', source_start_seconds=i,
        source_end_seconds=i + 1, rationale='测试边界') for i in range(count)]
    sources = media()
    sources[0].duration_seconds = 50
    timeline = TimelinePlanner().plan(sources, title='饮品', target_seconds=count * .3,
                                      recipe=EditRecipe.model_validate(payload))
    assert len(timeline.clips) == count
    assert timeline.actual_duration_seconds == pytest.approx(count * .3)


@pytest.mark.parametrize('field,value', [('material_id', 'other-product'), ('source_end_seconds', 11)])
def test_director_rejects_unavailable_footage(field, value):
    payload = recipe_payload()
    payload['director_plan']['beats'][0][field] = value
    with pytest.raises(ValueError, match='director_'):
        TimelinePlanner().plan(media(), title='饮品', recipe=EditRecipe.model_validate(payload))


def test_director_rejects_overlapping_reuse():
    payload = recipe_payload()
    payload['director_plan']['beats'][1].update(source_start_seconds=5, source_end_seconds=8)
    with pytest.raises(ValueError, match='director_.*overlap'):
        TimelinePlanner().plan(media(), title='饮品', recipe=EditRecipe.model_validate(payload))


def test_director_rejects_arbitrary_source_paths():
    payload = recipe_payload()
    payload['director_plan']['beats'][0]['source_path'] = 'private.mp4'
    with pytest.raises(ValidationError):
        EditRecipe.model_validate(payload)


def test_old_recipe_still_works_without_director():
    payload = recipe_payload()
    del payload['director_plan']
    timeline = TimelinePlanner().plan(media(), title='饮品', recipe=EditRecipe.model_validate(payload))
    assert timeline.engine == 'dify_enhanced'


@pytest.mark.parametrize('title', ['绿豆沙', '保温杯', '遮阳帽'])
def test_local_product_preview_does_not_invent_other_products_or_claims(title):
    task = SimpleNamespace(title=title, content_type='商品介绍', requirements_text='', tutorial_text='')
    narration = PipelineService._narration_text(task, target_seconds=22)
    assert title in narration
    assert all(word not in narration for word in ['除毛梳', '宠物', '修饰脸型', '轻量好收纳'])


def test_source_catalog_does_not_expose_local_paths():
    from app.services.director_service import material_catalog
    import json
    assert 'drink.mp4' not in json.dumps(material_catalog(media()))


def test_source_catalog_bounds_ocr_payload():
    import json
    from app.schemas.editing import FrameEvidence
    from app.services.director_service import material_catalog
    sources = media() * 30
    sources[0].frames = [FrameEvidence(timestamp_seconds=0, image_path='private.jpg', width=1,
                                     height=1, brightness=1, contrast=1, sharpness=1,
                                     ocr_texts=['字' * 10000] * 8)] * 30
    assert len(json.dumps(material_catalog(sources), ensure_ascii=False)) < 40000


def test_director_requires_hook_and_closing():
    payload = recipe_payload()
    payload['director_plan']['beats'][0]['purpose'] = 'feature'
    with pytest.raises(ValidationError, match='bookends'):
        EditRecipe.model_validate(payload)


def test_dify_no_consent_makes_no_provider_request(tmp_path):
    from app.config import Settings
    pipeline = PipelineService(Settings(data_dir=tmp_path))
    task = SimpleNamespace(tutorial_text='课程', cloud_processing_allowed=False)
    class Forbidden:
        def __getattr__(self, name):
            raise AssertionError('provider contacted without consent')
    pipeline.dify = Forbidden()
    warnings = []
    assert pipeline._analyze_tutorial(None, task, media(), tmp_path, [], warnings) is None
    assert pipeline._analyze_viral(None, task, tmp_path, [], warnings) is None
    assert len(warnings) == 2


def test_review_manifest_keeps_creative_state():
    from app.services.review_service import ReviewManifest
    manifest = ReviewManifest(aigc_declaration='AI', evidence=[], warnings=[],
                              publish_copy=[dict(title='a', body='b', topics=['c'])] * 3,
                              creative_validation={'semantic_match': 'unknown'})
    assert manifest.model_dump()['creative_validation']['semantic_match'] == 'unknown'


def test_repair_maps_names_clamps_bounds_drops_overlaps_and_restores_bookends():
    from app.schemas.director import DirectorPlan
    from app.schemas.editing import MediaAnalysis
    from app.services.director_service import repair_director_plan
    import pytest as _pytest

    analyses = [MediaAnalysis(material_id="aaaa1111-0000-0000-0000-000000000001", source_path="a.mov", duration_seconds=3.0,
                              width=1080, height=1920, has_audio=False),
                MediaAnalysis(material_id="bbbb2222-0000-0000-0000-000000000002", source_path="b.mov", duration_seconds=2.0,
                              width=1080, height=1920, has_audio=False)]
    beat = dict(narration="句子", rationale="r", source_start_seconds=0.0, source_end_seconds=1.0)
    plan = DirectorPlan(version=1, beats=[
        {**beat, "purpose": "hook", "material_id": "14.倒水-PMR05248.mov"},          # name alias -> a
        {**beat, "purpose": "feature", "material_id": "bbbb2222"},                   # unambiguous prefix -> b
        {**beat, "purpose": "feature", "material_id": "bbbb2222-0000-0000-0000-000000000002",
         "source_start_seconds": 1.5, "source_end_seconds": 9.0},                    # end clamped to 2.0
        {**beat, "purpose": "usage", "material_id": "aaaa1111-0000-0000-0000-000000000001",
         "source_start_seconds": 0.5, "source_end_seconds": 1.2},                    # overlaps beat 1 -> dropped
        {**beat, "purpose": "usage", "material_id": "unknown-file.mov"},              # dropped
        {**beat, "purpose": "closing", "material_id": "aaaa1111-0000-0000-0000-000000000001",
         "source_start_seconds": 2.0, "source_end_seconds": 2.9},
    ])
    repaired, notes = repair_director_plan(plan, analyses, aliases={"14.倒水-PMR05248.mov": "aaaa1111-0000-0000-0000-000000000001"})
    assert [(b.purpose, b.material_id[:4], b.source_start_seconds, b.source_end_seconds) for b in repaired.beats] == [
        ("hook", "aaaa", 0.0, 1.0), ("feature", "bbbb", 0.0, 1.0), ("feature", "bbbb", 1.5, 2.0), ("closing", "aaaa", 2.0, 2.9)]
    assert any("mapped to" in note for note in notes) and any("clamped" in note for note in notes)
    assert any("overlaps" in note for note in notes) and any("unknown material" in note for note in notes)

    hopeless = DirectorPlan(version=1, beats=[{**beat, "purpose": "hook", "material_id": "x.mov"},
                                             {**beat, "purpose": "closing", "material_id": "y.mov"}])
    with _pytest.raises(ValueError, match="director_plan_unrepairable"):
        repair_director_plan(hopeless, analyses)
