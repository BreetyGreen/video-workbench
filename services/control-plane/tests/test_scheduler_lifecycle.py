from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_scheduler_can_be_disabled_independently_from_daily_automation(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'scheduler.db').as_posix()}",
        automation_enabled=True,
        automation_scheduler_enabled=False,
    )

    with TestClient(create_app(settings)) as client:
        assert client.app.state.automation_scheduler_started is False
