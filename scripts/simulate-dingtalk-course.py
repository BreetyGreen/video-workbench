from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = PROJECT_ROOT / "fixtures" / "dingtalk" / "course-event.json"


def target_allowed(base_url: str, *, allow_remote: bool) -> bool:
    if allow_remote:
        return True
    parsed = urlparse(base_url)
    hostname = parsed.hostname or ""
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def load_fixture(path: Path) -> tuple[dict[str, object], list[tuple[str, tuple[str, bytes, str]]]]:
    fixture_path = path.resolve()
    fixture_root = fixture_path.parent
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    assets = payload.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("fixture_assets_required")

    files: list[tuple[str, tuple[str, bytes, str]]] = []
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("invalid_fixture_asset")
        source = (fixture_root / str(asset["path"])).resolve()
        if fixture_root not in source.parents:
            raise ValueError("fixture_path_outside_root")
        if not source.is_file():
            raise FileNotFoundError(
                f"fixture media missing: {source}. Run scripts/generate-course-fixture.ps1 first."
            )
        files.append(
            (
                "files",
                (
                    source.name,
                    source.read_bytes(),
                    str(asset["mime_type"]),
                ),
            )
        )
    return payload, files


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit a simulated DingTalk course event.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8130")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args()

    if not target_allowed(args.base_url, allow_remote=args.allow_remote):
        parser.error("remote target requires --allow-remote")

    payload, files = load_fixture(args.fixture)
    assets = payload.pop("assets")
    assert isinstance(assets, list)
    form = {
        **{key: str(value) for key, value in payload.items()},
        "asset_roles": json.dumps([asset["role"] for asset in assets]),
        "rights_statuses": json.dumps([asset["rights_status"] for asset in assets]),
    }
    response = httpx.post(
        args.base_url.rstrip("/") + "/api/courses/intake",
        data=form,
        files=files,
        timeout=120,
    )
    response.raise_for_status()
    course = response.json()
    print(
        json.dumps(
            {
                "id": course["id"],
                "status": course["status"],
                "asset_count": len(course["assets"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
