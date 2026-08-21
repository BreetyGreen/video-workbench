from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.models import UsageBudget, VideoTask
from app.services.usage_service import UsageService


def session_for(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{(tmp_path / 'ledger.db').as_posix()}")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_usage_service_aggregates_by_task_and_marks_unapplied(tmp_path: Path):
    with session_for(tmp_path) as session:
        service = UsageService()
        service.record_event(session, task_id="a", provider="volcengine", service="asr", metric="audio_seconds", quantity=29.089, unit="seconds")
        service.record_event(session, task_id="a", provider="volcengine", service="tts", metric="characters", quantity=40, unit="characters")
        service.record_event(session, task_id="a", provider="dify", service="dify_tutorial", metric="total_tokens", quantity=714, unit="tokens", status="succeeded_not_applied")
        service.record_event(session, task_id="b", provider="volcengine", service="tts", metric="characters", quantity=90, unit="characters")

        summary = service.task_usage(session, "a")

        assert summary["totals"]["asr_audio_seconds"] == 29.089
        assert summary["totals"]["tts_characters"] == 40
        assert summary["totals"]["total_tokens"] == 714
        assert summary["unapplied_calls"] == 1
        assert all(event["task_id"] == "a" for event in summary["events"])


def test_local_summary_calculates_thresholds(tmp_path: Path):
    with session_for(tmp_path) as session:
        session.add(UsageBudget(id="default", tts_total_characters=100, asr_total_seconds=100))
        session.commit()
        service = UsageService()
        service.record_event(session, task_id="a", provider="volcengine", service="tts", metric="characters", quantity=85, unit="characters")
        service.record_event(session, task_id="a", provider="volcengine", service="asr", metric="audio_seconds", quantity=95, unit="seconds")

        summary = service.local_summary(session)

        assert summary["tts"]["remaining"] == 15
        assert summary["tts"]["level"] == "warning"
        assert summary["asr"]["remaining"] == 5
        assert summary["asr"]["level"] == "critical"
        assert summary["tts"]["source"] == "local_estimated"


def test_recent_task_usage_is_a_named_per_video_ledger(tmp_path: Path):
    with session_for(tmp_path) as session:
        session.add(VideoTask(id="task-new", title="宠物除毛梳", content_type="商品介绍", rights_confirmed=True))
        session.add(VideoTask(id="task-old", title="宠物日常", content_type="通用短视频", rights_confirmed=True))
        session.commit()
        service = UsageService()
        service.record_event(session, task_id="task-new", provider="volcengine", service="tts", metric="characters", quantity=128, unit="characters")
        service.record_event(session, task_id="task-new", provider="dify", service="workflow", metric="total_tokens", quantity=930, unit="tokens")

        ledger = service.recent_task_usage(session, limit=10)

        assert ledger[0]["task_id"] == "task-new"
        assert ledger[0]["title"] == "宠物除毛梳"
        assert ledger[0]["source"] == "local_measured"
        assert ledger[0]["event_count"] == 2
        assert ledger[0]["totals"]["tts_characters"] == 128
        assert ledger[0]["totals"]["total_tokens"] == 930
