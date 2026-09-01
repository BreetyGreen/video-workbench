from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "fixtures" / "dingtalk" / "course-event.json"
SCRIPT = ROOT / "scripts" / "simulate-dingtalk-course.py"


def load_script():
    spec = importlib.util.spec_from_file_location("simulate_dingtalk_course", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixture_has_all_course_roles_and_no_credentials() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False).lower()

    assert {asset["role"] for asset in payload["assets"]} == {
        "tutorial",
        "reference",
        "material",
    }
    assert len([asset for asset in payload["assets"] if asset["role"] == "material"]) >= 3
    assert "client_secret" not in serialized
    assert "access_token" not in serialized
    assert "secret_access_key" not in serialized


def test_fixture_paths_stay_inside_fixture_directory() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    root = FIXTURE.parent.resolve()

    for asset in payload["assets"]:
        resolved = (root / asset["path"]).resolve()
        assert root in resolved.parents


def test_cli_allows_loopback_and_requires_explicit_remote_override() -> None:
    module = load_script()

    assert module.target_allowed("http://127.0.0.1:8130", allow_remote=False)
    assert module.target_allowed("http://localhost:8130", allow_remote=False)
    assert not module.target_allowed("https://video.example.com", allow_remote=False)
    assert module.target_allowed("https://video.example.com", allow_remote=True)
