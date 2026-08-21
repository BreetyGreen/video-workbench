from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'setup-page.db').as_posix()}",
        automation_enabled=False,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_setup_page_contains_local_first_flow(client: TestClient):
    page = client.get("/setup")

    assert page.status_code == 200
    assert "3 分钟完成本机检查" in page.text
    assert "本地模式现在就能用" in page.text
    assert "云服务均为可选增强" in page.text
    assert 'id="setup-runtime-list"' in page.text
    assert 'id="setup-provider-list"' in page.text
    assert 'id="confirm-local-mode"' in page.text
    assert 'aria-label="首次启动进度"' in page.text
    assert 'href="/"' in page.text
    assert "/static/setup.js" in page.text
    assert "/static/setup.css" in page.text


def test_setup_assets_are_served_and_use_real_apis(client: TestClient):
    stylesheet = client.get("/static/setup.css")
    script = client.get("/static/setup.js")

    assert stylesheet.status_code == 200
    assert ".setup-provider-list" in stylesheet.text
    assert "minmax(17.5rem, 1fr)" in stylesheet.text
    assert "prefers-reduced-motion" in stylesheet.text
    assert script.status_code == 200
    assert "/api/setup/status" in script.text
    assert "/api/setup/preferences" in script.text
    assert "/api/setup/validate/" in script.text
    assert "localStorage" not in script.text


def test_navigation_exposes_replayable_setup_assistant(client: TestClient):
    page = client.get("/setup")

    assert 'href="/setup"' in page.text
    assert "配置助手" in page.text
    assert 'aria-current="page"' in page.text
