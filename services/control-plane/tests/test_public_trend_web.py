import httpx
from pathlib import Path

from sqlmodel import Session, select

from app.adapters.public_trend_web import PublicTrendEvidence, PublicTrendWebClient
from app.config import Settings
from app.db import Database
from app.models import AutomationSchedule, TrendRecord
from app.services.automation_service import DailyAutomation


def test_public_trend_search_extracts_metadata_without_downloading_social_video():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            text='''
              <a class="result__a" href="https://www.douyin.com/video/123">三秒让猫咪主动梳毛</a>
              <a class="result__snippet">宠物梳毛教程，先展示沙发粘毛痛点。</a>
              <a class="result__a" href="https://example.com/other">无关结果</a>
            ''',
        )

    client = PublicTrendWebClient(
        enabled=True,
        transport=httpx.MockTransport(handler),
    )
    results = client.search("宠物", count=3)

    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert results[0].source == "douyin_public_web"
    assert results[0].url == "https://www.douyin.com/video/123"
    assert results[0].title == "三秒让猫咪主动梳毛"


def test_public_trend_search_can_be_disabled():
    assert PublicTrendWebClient(enabled=False).status()["status"] == "disabled"


def test_daily_automation_uses_public_metadata_when_official_search_is_missing(tmp_path: Path):
    class MissingDouyin:
        def status(self):
            return {"status": "not_configured"}

    class PublicEvidence:
        enabled = True

        def search(self, keyword: str, *, count: int):
            return [
                PublicTrendEvidence(
                    source="douyin_public_web",
                    item_id="video-123",
                    title="三秒让猫咪主动梳毛",
                    url="https://www.douyin.com/video/123",
                    summary="先展示沙发粘毛痛点",
                )
            ]

    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'trend.db').as_posix()}",
        automation_auto_create_tasks=False,
    )
    database = Database(settings.database_url)
    database.create_all()
    automation = DailyAutomation(
        settings,
        pipeline=object(),
        douyin=MissingDouyin(),
        public_trends=PublicEvidence(),
    )
    with Session(database.engine) as session:
        schedule = AutomationSchedule(keywords_json='["宠物"]')
        session.add(schedule)
        session.commit()
        run = automation.run(session, schedule, trigger="manual")
        records = list(session.exec(select(TrendRecord)).all())

    assert run.trend_status == "public_web_completed"
    assert len(records) == 1
    assert records[0].source == "douyin_public_web"
    assert records[0].high_quality_text == "先展示沙发粘毛痛点"
