from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_local_runtime_status_is_non_secret_and_actionable(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'runtime.db').as_posix()}",
        automation_enabled=False,
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/local-runtime")

    assert response.status_code == 200
    payload = response.json()
    assert payload["platform"]
    assert payload["architecture"]
    assert "jianying" in payload
    assert payload["runtime"]["data_dir"] == str(tmp_path / "data")
    assert "inbox_dir" in payload["runtime"]
    assert "api_key" not in response.text.lower()
    assert "access_token" not in response.text.lower()
