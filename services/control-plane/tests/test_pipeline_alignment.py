from types import SimpleNamespace
from pathlib import Path

from app.config import Settings
from app.schemas.editing import TranscriptResult, TranscriptSegment, TranscriptWord
from app.services.pipeline_service import PipelineService


def test_final_audio_is_transcribed_once_with_task_consent(tmp_path, monkeypatch):
    calls = []
    def transcribe(path, **kwargs):
        calls.append((path, kwargs))
        return TranscriptResult(provider='volcano_bigasr', model='test', duration_seconds=3,
            segments=[TranscriptSegment(text='你好', start_seconds=.5, end_seconds=2,
                words=[TranscriptWord(text='你好', start_seconds=.5, end_seconds=2)])])
    pipeline = PipelineService(Settings(data_dir=tmp_path))
    pipeline.analyzer.transcriber = SimpleNamespace(transcribe=transcribe)
    usage = []
    monkeypatch.setattr(pipeline, '_record_usage', lambda *a, **kw: usage.append(kw))
    task = SimpleNamespace(id='t', quality_profile='production', cloud_processing_allowed=False)
    result = pipeline._align_voiceover(None, task, Path('fitted.wav'), '你好', 3, tmp_path, [])
    assert result.status == 'word_aligned'
    assert result.captions[0].start_seconds == .5
    assert calls == [(Path('fitted.wav'), {'quality_profile':'production', 'cloud_processing_allowed':False})]
    assert usage[0]['quantity'] == 3
    assert usage[0]['metadata']['purpose'] == 'narration_alignment'
    assert (tmp_path / 'narration-alignment.json').exists()


def test_disabled_transcription_retains_explicit_estimate(tmp_path):
    pipeline = PipelineService(Settings(data_dir=tmp_path, transcription_enabled=False))
    result = pipeline._align_voiceover(None, None, Path('unused'), '你好', 3, tmp_path, [])
    assert result.status == 'unavailable'
    assert result.reason == 'transcription_disabled'


def test_probe_tolerance_does_not_extend_captions_past_final_video(tmp_path):
    pipeline = PipelineService(Settings(data_dir=tmp_path))
    transcript = TranscriptResult(segments=[TranscriptSegment(text='你好', start_seconds=0, end_seconds=3.03,
        words=[TranscriptWord(text='你好', start_seconds=0, end_seconds=3.03)])])
    pipeline.analyzer.transcriber = SimpleNamespace(transcribe=lambda *a, **kw: transcript)
    task = SimpleNamespace(quality_profile='production', cloud_processing_allowed=False)
    result = pipeline._align_voiceover(None, task, Path('fitted.wav'), '你好', 3, tmp_path, [])
    assert result.captions == []
    assert result.reason == 'caption_exceeds_final_timeline'


def test_title_card_only_for_short_product_names():
    from app.schemas.editing import EditingTimeline, TimelineClip
    from app.services.pipeline_service import PipelineService

    def timeline(title, seconds=5.0):
        return EditingTimeline(title=title, target_duration_seconds=seconds, actual_duration_seconds=seconds,
                               clips=[TimelineClip(material_id="m", source_path="m.mp4", source_start_seconds=0,
                                                   source_end_seconds=seconds, timeline_start_seconds=0,
                                                   timeline_end_seconds=seconds, score=1, reason="hook:x",
                                                   has_audio=False)])

    card = PipelineService._title_card(timeline("果知纯 绿豆沙"))
    assert card is not None
    assert card.text == "果知纯绿豆沙"
    assert card.style == "title" and card.placement == "middle"
    assert (card.start_seconds, card.end_seconds) == (0.0, 1.4)
    assert PipelineService._title_card(timeline("绿豆沙", seconds=0.9)) is None
    assert PipelineService._title_card(timeline("绿豆沙-正式流水线实剪-20260909")) is None
    short = PipelineService._title_card(timeline("绿豆沙", seconds=1.0))
    assert short is not None and short.end_seconds == 1.0
