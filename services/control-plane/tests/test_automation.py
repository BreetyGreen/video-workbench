from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.douyin import DouyinSearchClient
from app.adapters.douyin import DouyinVideo
from app.config import Settings
from app.main import create_app
from app.models import AutomationSchedule
from app.services.automation_service import DailyAutomation


def douyin_settings(**overrides) -> Settings:
    values = {
        "douyin_client_key": "client-key",
        "douyin_client_secret": "client-secret",
        "douyin_device_id": 8241677744935186821,
    }
    values.update(overrides)
    return Settings(**values)


def test_douyin_search_uses_official_token_and_search_endpoints():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/oauth/client_token/":
            assert json.loads(request.content)["grant_type"] == "client_credential"
            return httpx.Response(
                200,
                json={
                    "data": {"access_token": "clt-token", "error_code": 0, "expires_in": 7200},
                    "message": "success",
                },
            )
        assert request.url.path == "/dy_open_api/v1/search/video/"
        assert request.headers["access-token"] == "clt-token"
        assert request.url.params["keyword"] == "宠物"
        assert request.url.params["sort_type"] == "1"
        assert request.url.params["publish_time"] == "7"
        return httpx.Response(
            200,
            json={
                "err_no": 0,
                "err_msg": "success",
                "data": {
                    "data": {
                        "cursor": 1,
                        "has_more": False,
                        "search_id": "search-1",
                        "video_list": [
                            {
                                "item_id": "video-1",
                                "title": "宠物的一天",
                                "cover": "https://example.test/cover.jpg",
                                "create_time": 1786000000,
                                "avatar": "https://example.test/avatar.jpg",
                                "nickname": "作者",
                                "statistics": {"digg_count": 12345},
                                "link": "https://www.douyin.com/video/video-1",
                                "high_quality_text": "公开视频文字",
                            }
                        ],
                    }
                },
            },
        )

    client = DouyinSearchClient(douyin_settings(), transport=httpx.MockTransport(handler))

    result = client.search("宠物", count=10, publish_time=7, sort_type=1)

    assert result[0].item_id == "video-1"
    assert result[0].digg_count == 12345
    assert [request.url.path for request in requests] == [
        "/oauth/client_token/",
        "/dy_open_api/v1/search/video/",
    ]


def test_douyin_search_reports_missing_permission_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/client_token/":
            return httpx.Response(
                200,
                json={"data": {"access_token": "token", "error_code": 0, "expires_in": 7200}},
            )
        return httpx.Response(200, json={"err_no": 28001018, "err_msg": "应用未获得该能力"})

    client = DouyinSearchClient(douyin_settings(), transport=httpx.MockTransport(handler))

    with pytest.raises(RuntimeError, match="28001018"):
        client.search("宠物")


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'automation.db').as_posix()}",
        automation_enabled=False,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_daily_schedule_can_be_configured_and_read(client: TestClient):
    response = client.put(
        "/api/automations/daily",
        json={
            "enabled": True,
            "hour": 8,
            "minute": 30,
            "timezone": "Asia/Shanghai",
            "keywords": ["宠物", "萌宠"],
        },
    )

    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert response.json()["keywords"] == ["宠物", "萌宠"]
    current = client.get("/api/automations/daily")
    assert current.json() == response.json()


def test_manual_trend_import_deduplicates_same_source_item(client: TestClient):
    payload = {
        "records": [
            {
                "source": "manual",
                "keyword": "宠物",
                "item_id": "video-1",
                "title": "宠物的一天",
                "url": "https://www.douyin.com/video/video-1",
                "digg_count": 12345,
                "author": "作者",
                "captured_at": datetime.now(UTC).isoformat(),
                "evidence": "人工导入的公开页面指标",
            }
        ]
    }

    first = client.post("/api/trends/import", json=payload)
    second = client.post("/api/trends/import", json=payload)
    records = client.get("/api/trends?limit=20")

    assert first.json()["inserted"] == 1
    assert second.json()["inserted"] == 0
    assert len(records.json()) == 1
    assert records.json()[0]["source_type"] == "public"


def test_manual_daily_run_records_explicit_unconfigured_trend_status(client: TestClient):
    configured = client.put(
        "/api/automations/daily",
        json={
            "enabled": True,
            "hour": 8,
            "minute": 30,
            "timezone": "Asia/Shanghai",
            "keywords": ["宠物"],
        },
    )
    assert configured.status_code == 200

    response = client.post("/api/automations/daily/run")

    assert response.status_code == 200
    assert response.json()["status"] == "completed_with_warnings"
    assert response.json()["trend_status"] == "not_configured"
    assert response.json()["processed_tasks"] == 0


def test_daily_schedule_runs_once_after_local_time_and_not_twice_same_day():
    automation = DailyAutomation(douyin_settings(), pipeline=None, douyin=None)  # type: ignore[arg-type]
    schedule = AutomationSchedule(
        enabled=True,
        hour=8,
        minute=30,
        timezone="Asia/Shanghai",
    )

    assert automation.is_due(schedule, datetime(2026, 8, 17, 0, 29, tzinfo=UTC)) is False
    assert automation.is_due(schedule, datetime(2026, 8, 17, 0, 30, tzinfo=UTC)) is True

    schedule.last_run_at = datetime(2026, 8, 17, 0, 30, tzinfo=UTC)
    assert automation.is_due(schedule, datetime(2026, 8, 17, 10, 0, tzinfo=UTC)) is False
    assert automation.is_due(schedule, datetime(2026, 8, 18, 0, 30, tzinfo=UTC)) is True


def test_trend_radar_page_and_explicit_unconfigured_discovery(client: TestClient):
    page = client.get("/trends")
    discovery = client.post("/api/trends/discover", json={"keyword": "宠物梳毛", "count": 10})

    assert page.status_code == 200
    assert "热点雷达" in page.text
    assert "抖音官方搜索" in page.text
    assert "小红书证据导入" in page.text
    assert 'id="trend-results"' in page.text
    assert "/static/trends.js" in page.text
    assert discovery.status_code == 409
    assert discovery.json()["detail"]["code"] == "douyin_not_configured"


def test_trend_discovery_uses_official_douyin_client_and_persists_evidence(tmp_path: Path):
    class FakeDouyin:
        def status(self):
            return {"status": "configured"}

        def search(self, keyword: str, *, count: int, publish_time: int, sort_type: int):
            assert (keyword, count, publish_time, sort_type) == ("宠物梳毛", 8, 7, 1)
            return [
                DouyinVideo(
                    item_id="official-video-1",
                    title="宠物梳毛前后对比",
                    cover_url="https://example.test/cover.jpg",
                    published_at=datetime.now(UTC),
                    author="公开作者",
                    digg_count=23456,
                    url="https://www.douyin.com/video/official-video-1",
                    high_quality_text="沙发不再粘毛",
                )
            ]

    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'trend-discovery.db').as_posix()}",
        automation_enabled=False,
    )
    with TestClient(create_app(settings, douyin_search_client=FakeDouyin())) as test_client:
        response = test_client.post("/api/trends/discover", json={"keyword": "宠物梳毛", "count": 8})
        records = test_client.get("/api/trends").json()

    assert response.status_code == 200
    assert response.json()["inserted"] == 1
    assert response.json()["results"][0]["digg_count"] == 23456
    assert records[0]["source"] == "douyin_official_search"
    assert "抖音开放平台" in records[0]["evidence"]


def test_xiaohongshu_evidence_import_requires_public_url_and_keeps_source(client: TestClient):
    response = client.post(
        "/api/trends/xiaohongshu/import",
        json={
            "keyword": "宠物梳毛",
            "title": "梳毛前后对比",
            "url": "https://www.xiaohongshu.com/explore/example-note",
            "author": "公开笔记作者",
            "engagement_count": 3210,
            "evidence_note": "人工核对的公开页面数据，抓取日期 2026-08-20",
        },
    )
    invalid = client.post(
        "/api/trends/xiaohongshu/import",
        json={
            "keyword": "宠物",
            "title": "错误链接",
            "url": "https://example.com/not-xhs",
            "evidence_note": "人工核对",
        },
    )

    assert response.status_code == 200
    assert response.json()["inserted"] == 1
    record = client.get("/api/trends").json()[0]
    assert record["source"] == "xiaohongshu_evidence"
    assert record["url"].startswith("https://www.xiaohongshu.com/")
    assert invalid.status_code == 422
