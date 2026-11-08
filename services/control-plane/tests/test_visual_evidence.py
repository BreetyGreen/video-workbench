from pathlib import Path

from PIL import Image
import pytest

from app.schemas.editing import FrameEvidence, MediaAnalysis
from app.services import director_service


def source(root, identifier='m', count=5):
    frames = []
    for i in range(count):
        path = root / f'{identifier}-{i}.png'
        Image.new('RGB', (8, 8), (i, 30, 60)).save(path)
        frames.append(FrameEvidence(timestamp_seconds=i, image_path=str(path), width=8,
                                    height=8, brightness=30, contrast=1, sharpness=1))
    return MediaAnalysis(material_id=identifier, source_path='private-source.mp4',
                         duration_seconds=10, width=8, height=8, has_audio=False, frames=frames)


def test_samples_across_materials_and_time_without_paths_in_manifest(tmp_path):
    sources = [source(tmp_path, str(i)) for i in range(6)]
    paths, manifest = director_service.visual_frame_inputs(sources, tmp_path)
    assert len(paths) == 8
    assert [m['material_id'] for m in manifest[:6]] == [str(i) for i in range(6)]
    assert [m['timestamp_seconds'] for m in manifest] == [0] * 6 + [4, 4]
    assert [m['image_index'] for m in manifest] == list(range(1, 9))
    assert all(set(m) == {'image_index', 'material_id', 'timestamp_seconds'} for m in manifest)
    assert all(isinstance(p, Path) for p in paths)


@pytest.mark.parametrize('bad', ['outside', 'missing', 'corrupt', 'timestamp'])
def test_excludes_unsafe_or_unusable_frames(tmp_path, bad):
    root = tmp_path / 'analysis'
    root.mkdir()
    item = source(root, count=1)
    if bad == 'outside':
        other = source(tmp_path, 'outside', count=1)
        item.frames = other.frames
    elif bad == 'missing':
        item.frames[0].image_path = str(root / 'missing.png')
    elif bad == 'corrupt':
        # An existing non-image file must never be sent as a frame.
        Path(item.frames[0].image_path).write_bytes(b'not an image')
    else:
        item.frames[0].timestamp_seconds = 99
    assert director_service.visual_frame_inputs([item], root) == ([], [])


def test_zero_frames_stays_text_only(tmp_path):
    assert director_service.visual_frame_inputs([], tmp_path) == ([], [])


def test_reference_has_reserved_budget_and_cannot_be_editable(tmp_path):
    materials = [source(tmp_path, str(i)) for i in range(10)]
    reference = source(tmp_path, 'reference')
    paths, manifest = director_service.role_visual_frame_inputs(materials, tmp_path, reference=reference)
    assert len(paths) == 8
    assert sum(m['role'] == 'reference_not_editable' for m in manifest) == 2
    assert sum(m['role'] == 'editable_material' for m in manifest) == 6
    assert [m['image_index'] for m in manifest] == list(range(1, 9))
    assert all('image_path' not in m for m in manifest)


def test_without_reference_keeps_full_material_budget(tmp_path):
    paths, manifest = director_service.role_visual_frame_inputs([source(tmp_path, str(i)) for i in range(5)], tmp_path)
    assert len(paths) == 8
    assert all(m['role'] == 'editable_material' for m in manifest)


def test_tutorial_and_reference_reserve_bounded_distinct_role_frames(tmp_path):
    root = tmp_path / 'tasks'
    root.mkdir()
    tutorials_root = tmp_path / 'courses'
    tutorials_root.mkdir()
    materials = [source(root, f'm{i}') for i in range(8)]
    tutorials = [source(tutorials_root, f't{i}') for i in range(3)]
    paths, manifest = director_service.role_visual_frame_inputs(
        materials, root, reference=source(root, 'r'), tutorials=tutorials,
        tutorial_root=tutorials_root)
    assert len(paths) == 8
    assert [m['role'] for m in manifest].count('editable_material') == 4
    assert [m['role'] for m in manifest].count('reference_not_editable') == 2
    teaching = [m for m in manifest if m['role'] == 'tutorial_not_editable']
    assert [m['material_id'] for m in teaching] == ['t0', 't1']
    assert [m['image_index'] for m in manifest] == list(range(1, 9))


def test_tutorial_frames_outside_default_root_are_not_loaded(tmp_path):
    root = tmp_path / 'tasks'
    root.mkdir()
    paths, manifest = director_service.role_visual_frame_inputs(
        [], root, tutorials=[source(tmp_path, 'tutorial')])
    assert paths == manifest == []


@pytest.fixture
def tutorial_session():
    from sqlmodel import SQLModel, Session, create_engine
    from app.models import Course, EditingRecipe
    engine = create_engine('sqlite://')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Course(id='course', title='c', source_message_id='m'))
        session.add(EditingRecipe(id='recipe', course_id='course', title='r'))
        session.commit()
        yield session
    engine.dispose()


def add_tutorial(session, root, identifier='tutorial', role='tutorial', mime='video/mp4'):
    from app.models import CourseAsset
    video = root / f'{identifier}.mp4'
    video.write_bytes(b'fixture')
    analysis = source(root, identifier)
    video.with_suffix('.tutorial-analysis.json').write_text(analysis.model_dump_json(), encoding='utf-8')
    session.add(CourseAsset(id=identifier, course_id='course', role=role,
        original_name=video.name, stored_path=str(video), mime_type=mime,
        size_bytes=7, sha256=identifier))
    session.commit()
    return video


def test_loads_only_two_course_tutorial_analyses(tutorial_session, tmp_path):
    assert hasattr(director_service, 'load_course_tutorial_analyses')
    for i in range(3):
        add_tutorial(tutorial_session, tmp_path, f't{i}')
    analyses = director_service.load_course_tutorial_analyses(tutorial_session, 'recipe', tmp_path)
    assert [a.material_id for a in analyses] == ['t0', 't1']


@pytest.mark.parametrize('bad', ['role', 'mime', 'outside', 'schema', 'id', 'oversized', 'missing_recipe'])
def test_tutorial_analysis_rejects_wrong_role_path_or_schema(tutorial_session, tmp_path, bad):
    assert hasattr(director_service, 'load_course_tutorial_analyses')
    root = tmp_path / 'data'
    root.mkdir()
    video = add_tutorial(tutorial_session, tmp_path if bad == 'outside' else root,
        role='material' if bad == 'role' else 'tutorial', mime='text/plain' if bad == 'mime' else 'video/mp4')
    sidecar = video.with_suffix('.tutorial-analysis.json')
    if bad == 'schema':
        sidecar.write_text('{}', encoding='utf-8')
    elif bad == 'id':
        sidecar.write_text(source(root, 'wrong-id').model_dump_json(), encoding='utf-8')
    elif bad == 'oversized':
        sidecar.write_bytes(b' ' * (4 * 1024 * 1024 + 1))
    assert director_service.load_course_tutorial_analyses(
        tutorial_session, 'absent' if bad == 'missing_recipe' else 'recipe', root) == []


def test_published_revision_enables_exact_input_reuse_without_double_usage(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.config import Settings
    from app.schemas.analysis import EditRecipe
    from app.services.pipeline_service import PipelineService
    calls = []
    recipe = EditRecipe(hook_rules=['hook'], target_duration_seconds=10,
                        pacing=[{'from_second':0,'to_second':10,'instruction':'cut'}], track_layout=['video'],
                        caption_style='white', audio_rules=[], prohibited_elements=[],
                        qa_thresholds={'max_silence_seconds':1, 'max_black_seconds':1})
    dify = SimpleNamespace(analyze_tutorial=lambda *a, **kw: calls.append(1) or recipe, last_usage=None)
    pipeline = PipelineService(Settings(data_dir=tmp_path, dify_base_url='http://test/v1',
        dify_tutorial_api_key='test-only', dify_tutorial_workflow_revision='published-r1'), dify=dify)
    usage = []
    monkeypatch.setattr(pipeline, '_record_dify_usage', lambda *a, **kw: usage.append(1))
    task = SimpleNamespace(tutorial_text='教程', cloud_processing_allowed=True,
                           requirements_text='看包装', content_type='商品')
    for _ in range(2):
        assert pipeline._analyze_tutorial(None, task, [], tmp_path, [], []) == recipe
    assert len(calls) == len(usage) == 1


def test_local_preflight_failure_never_records_previous_cloud_usage(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.config import Settings
    from app.services.pipeline_service import PipelineService
    import app.services.pipeline_service as module
    pipeline = PipelineService(Settings(data_dir=tmp_path, dify_base_url='http://test/v1',
        dify_tutorial_api_key='test-only'))
    pipeline.dify.last_usage = SimpleNamespace(total_tokens=71)
    def broken(*args):
        raise OSError('local preflight failure')
    monkeypatch.setattr(module, 'load_course_tutorial_analyses', broken)
    recorded = []
    monkeypatch.setattr(pipeline, '_record_dify_usage', lambda *a, **kw: recorded.append(1))
    task = SimpleNamespace(tutorial_text='教程', cloud_processing_allowed=True)
    assert pipeline._analyze_tutorial(None, task, [], tmp_path, [], []) is None
    assert recorded == []


def test_duplicate_frames_are_not_uploaded_twice(tmp_path):
    item = source(tmp_path, count=1)
    item.frames *= 5
    paths, manifest = director_service.visual_frame_inputs([item, item], tmp_path)
    assert len(paths) == len(manifest) == 1


def test_truncated_jpeg_is_excluded_even_when_header_verifies(tmp_path):
    item = source(tmp_path, count=1)
    path = tmp_path / 'truncated.jpg'
    Image.new('RGB', (64, 64), 'red').save(path)
    path.write_bytes(path.read_bytes()[:-40])
    item.frames[0].image_path = str(path)
    assert director_service.visual_frame_inputs([item], tmp_path) == ([], [])


def test_no_consent_resets_visual_report_and_never_selects_frames(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from app.config import Settings
    from app.services.pipeline_service import PipelineService
    import app.services.pipeline_service as module
    def forbidden(*args):
        raise AssertionError('frame access without consent')
    monkeypatch.setattr(module, 'visual_frame_inputs', forbidden)
    pipeline = PipelineService(Settings(data_dir=tmp_path))
    task = SimpleNamespace(tutorial_text='教程', cloud_processing_allowed=False)
    assert pipeline._analyze_tutorial(None, task, [], tmp_path, [], []) is None
    report = json.loads((tmp_path / 'visual-input-evidence.json').read_text())
    assert report['transport_status'] == 'not_sent'
    assert report['frames'] == []


def test_upload_failure_records_partial_unknown_without_retry(tmp_path, monkeypatch):
    import json
    import httpx
    from types import SimpleNamespace
    from app.adapters.dify import DifyClient
    from app.config import Settings
    from app.services.pipeline_service import PipelineService
    requests = []
    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(403, json={'code': 'forbidden'})
    settings = Settings(data_dir=tmp_path, dify_base_url='http://test.invalid/v1',
                        dify_tutorial_api_key='test-placeholder')
    pipeline = PipelineService(settings, dify=DifyClient(settings, transport=httpx.MockTransport(handler)))
    accounting = []
    monkeypatch.setattr(pipeline, '_record_dify_usage', lambda *args, **kwargs: accounting.append(kwargs))
    task = SimpleNamespace(tutorial_text='教程', cloud_processing_allowed=True,
                           requirements_text='看包装', content_type='商品')
    warnings = []
    assert pipeline._analyze_tutorial(None, task, [source(tmp_path)], tmp_path, [], warnings) is None
    assert requests == ['/v1/files/upload']
    report = json.loads((tmp_path / 'visual-input-evidence.json').read_text())
    assert report['transport_status'] == 'failed_or_partial'
    assert report['model_visual_use'] == 'unknown'
    assert accounting == [dict(workflow='tutorial', applied=False)]
    assert pipeline.dify.last_usage is None
    assert any('回退' in warning for warning in warnings)


@pytest.mark.parametrize('provider_status', ['failed', 'stopped'])
def test_failed_workflow_retains_tokens_without_success_label(tmp_path, monkeypatch, provider_status):
    import httpx
    from types import SimpleNamespace
    from app.adapters.dify import DifyClient
    from app.config import Settings
    from app.services.pipeline_service import PipelineService
    settings = Settings(data_dir=tmp_path, dify_base_url='http://test.invalid/v1',
                        dify_tutorial_api_key='test-placeholder')
    dify = DifyClient(settings, transport=httpx.MockTransport(lambda request: httpx.Response(200,
        json={'data': {'id': 'failed-run', 'status': provider_status, 'total_tokens': 17}})))
    with pytest.raises(RuntimeError):
        dify.analyze_tutorial({})
    pipeline = PipelineService(settings, dify=dify)
    events = []
    monkeypatch.setattr(pipeline, '_record_usage', lambda *args, **kwargs: events.append(kwargs))
    pipeline._record_dify_usage(None, SimpleNamespace(id='task'), [], workflow='tutorial', applied=False)
    total = next(e for e in events if e['metric'] == 'total_tokens')
    assert total['quantity'] == 17
    assert total['status'] == provider_status
