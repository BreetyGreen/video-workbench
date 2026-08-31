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
    assert "本地剪辑无需 Key" in page.text
    assert "云服务均为可选增强" in page.text
    assert 'id="setup-runtime-list"' in page.text
    assert 'id="setup-provider-list"' in page.text
    assert 'id="setup-capability-list"' in page.text
    assert 'id="confirm-local-mode"' in page.text
    assert 'aria-label="首次启动进度"' in page.text
    assert 'href="/"' in page.text
    assert 'href="/docs/capabilities-and-configuration"' in page.text
    assert "/static/setup.js" in page.text
    assert "/static/setup.css" in page.text


def test_setup_assets_are_served_and_use_real_apis(client: TestClient):
    stylesheet = client.get("/static/setup.css")
    script = client.get("/static/setup.js")

    assert stylesheet.status_code == 200
    assert ".setup-provider-list" in stylesheet.text
    assert ".setup-capability-list" in stylesheet.text
    assert "minmax(17.5rem, 1fr)" in stylesheet.text
    assert "grid-template-columns: repeat(4, minmax(0, 1fr))" in stylesheet.text
    assert ".setup-head > *," in stylesheet.text
    assert "prefers-reduced-motion" in stylesheet.text
    assert script.status_code == 200
    assert "/api/setup/status" in script.text
    assert "status.capabilities" in script.text
    assert "runtime.runtime?.data_dir" in script.text
    assert "runtime.runtime?.inbox_dir" in script.text
    assert "/api/setup/preferences" in script.text
    assert "/api/setup/validate/" in script.text
    assert "localStorage" not in script.text


def test_navigation_exposes_replayable_setup_assistant(client: TestClient):
    page = client.get("/setup")

    assert 'href="/setup"' in page.text
    assert "配置助手" in page.text
    assert 'aria-current="page"' in page.text


def test_capability_guide_is_available_inside_the_local_app(client: TestClient):
    guide = client.get("/docs/capabilities-and-configuration")

    assert guide.status_code == 200
    assert "剪辑能力与配置完整指南" in guide.text
    assert "本地剪辑不需要 Key" in guide.text
    assert 'id="local-editing"' in guide.text

    main_source = (Path(__file__).parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert 'parents[3] / "docs"' not in main_source
    assert '"capabilities.html"' in main_source
