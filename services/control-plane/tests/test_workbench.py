from __future__ import annotations

from pathlib import Path
import re

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_workbench_page_and_operational_lists(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'workbench.db').as_posix()}",
        automation_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        confirmation = client.put("/api/setup/preferences", json={"local_mode_confirmed": True})
        assert confirmation.status_code == 200
        page = client.get("/")
        assert page.status_code == 200
        assert "视频生产控制台" in page.text
        assert "今天想让观众记住什么？" in page.text
        assert 'class="creation-prompt"' in page.text
        assert '<input type="hidden" name="content_type" value="通用短视频">' in page.text
        assert 'class="preset-chip active"' in page.text
        assert 'data-content-type="商品介绍"' in page.text
        assert 'class="advanced-settings"' in page.text
        assert "高级设置" in page.text
        assert 'id="asset-summary"' in page.text
        assert 'id="creation-preflight"' in page.text
        assert "生成视频方案" in page.text
        assert "每日自动化" in page.text
        assert "云端余量" in page.text
        assert 'aria-label="主导航"' in page.text
        assert 'class="app-sidebar"' in page.text
        assert 'class="app-mobilebar"' in page.text
        assert 'class="app-main workspace"' in page.text
        assert '/static/design_system.css' in page.text
        assert 'href="/"' in page.text
        assert 'href="/settings/cloud-usage"' in page.text
        assert 'href="/voices"' in page.text
        assert 'href="/trends"' in page.text
        assert 'id="cloud-usage-cards"' in page.text
        assert 'id="local-runtime-status"' in page.text
        assert "路径会自动发现" in page.text
        assert 'id="setup-progress"' in page.text
        assert 'href="/setup"' in page.text
        assert 'id="show-archived"' in page.text
        assert "查看归档" in page.text
        assert 'name="quality_profile"' in page.text
        assert "生产高质量" in page.text
        assert 'name="cloud_processing_allowed"' in page.text
        assert 'name="reference_file"' in page.text
        assert 'name="voice_preset"' in page.text
        assert 'value="vivi-2"' in page.text
        assert '官方音色中心' in page.text
        assert "/static/workbench.js" in page.text
        assert re.search(r'/static/workbench\.js\?v=[a-f0-9]{12}', page.text)

        tasks = client.get("/api/tasks")
        assert tasks.status_code == 200
        assert tasks.json() == []

        run = client.post("/api/automations/daily/run")
        assert run.status_code == 200
        runs = client.get("/api/automations/runs")
        assert runs.status_code == 200
        assert runs.json()[0]["id"] == run.json()["id"]


def test_first_visit_guides_without_forcing_setup(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'first-visit.db').as_posix()}",
        automation_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        page = client.get("/", follow_redirects=False)

        assert page.status_code == 200
        assert 'id="first-run-guide"' in page.text
        assert 'data-first-run="true"' in page.text
        assert "本地剪辑不需要 Key" in page.text
        assert 'href="/setup"' in page.text
        assert 'id="skip-first-run"' in page.text

        skipped = client.put("/api/setup/preferences", json={"local_mode_confirmed": True})
        assert skipped.status_code == 200
        revisited = client.get("/")
        assert 'data-first-run="false"' in revisited.text


def test_workbench_assets_are_served(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'assets.db').as_posix()}",
        automation_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        stylesheet = client.get("/static/workbench.css")
        script = client.get("/static/workbench.js")

        assert stylesheet.status_code == 200
        assert "--accent" in stylesheet.text
        assert ".sr-only" in stylesheet.text
        assert "left: 0" in stylesheet.text
        assert script.status_code == 200
        assert "loadWorkbench" in script.text
        assert "loadCloudUsage" in script.text
        assert "loadLocalRuntime" in script.text
        assert "loadSetupProgress" in script.text
        assert "dismissFirstRunGuide" in script.text
        assert 'body: JSON.stringify({ local_mode_confirmed: true })' in script.text
        assert "/api/setup/status" in script.text
        assert "updateCreationPreflight" in script.text
        assert "bindCreationControls" in script.text
        assert "/api/cloud-usage/refresh" in script.text
        assert "include_archived" in script.text
        assert "/restore" in script.text
        assert "方舟 30 天 Token" not in script.text
        assert "方舟免费额度" in script.text
        assert "跨模型合计" in script.text
        assert "官方未返回 Token 明细" in script.text
        assert "未知" in script.text

        review_stylesheet = client.get("/static/review.css")
        assert review_stylesheet.status_code == 200
        assert ".grid > * { min-width: 0; }" in review_stylesheet.text
        assert "overflow-wrap: anywhere" in review_stylesheet.text

        navigation_stylesheet = client.get("/static/app_nav.css")
        assert navigation_stylesheet.status_code == 200
        assert ".app-sidebar" in navigation_stylesheet.text
        assert ".app-mobilebar" in navigation_stylesheet.text
        assert "@media (max-width: 900px)" in navigation_stylesheet.text

        design_system = client.get("/static/design_system.css")
        assert design_system.status_code == 200
        assert "--color-accent" in design_system.text
        assert "oklch(" in design_system.text
        assert "prefers-reduced-motion" in design_system.text
