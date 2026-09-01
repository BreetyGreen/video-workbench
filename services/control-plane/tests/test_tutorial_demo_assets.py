from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.services.tutorial_demo_assets import TutorialDemoAssetService


def test_demo_manifest_has_auditable_licensed_sources(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    service = TutorialDemoAssetService(settings)

    manifest = service.load_manifest()

    assert len(manifest["materials"]) >= 2
    for item in manifest["materials"]:
        assert item["file_page"].startswith("https://commons.wikimedia.org/wiki/File:")
        assert item["download_url"].startswith("https://commons.wikimedia.org/wiki/Special:Redirect/file/")
        assert item["author"]
        assert item["license"] in {"CC0-1.0", "CC-BY-4.0"}
        assert item["license_url"].startswith("https://creativecommons.org/")
        assert isinstance(item["attribution_required"], bool)
        assert item["expected_duration_seconds"] > 1
        assert item["expected_mime_type"].startswith("video/")
        assert len(item["expected_sha256"]) == 64
        assert not item.get("synthetic_fallback", False)


def test_download_failure_creates_labeled_synthetic_fallback_and_rights_ledger(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")

    def fail_download(url: str, destination: Path, maximum_bytes: int) -> None:
        raise RuntimeError("offline-fixture")

    service = TutorialDemoAssetService(settings, downloader=fail_download)
    output = service.prepare_materials(tmp_path / "run")
    ledger = json.loads(output.rights_ledger_path.read_text(encoding="utf-8"))

    assert len(output.material_paths) >= 2
    assert all(path.is_file() and path.stat().st_size > 0 for path in output.material_paths)
    assert all(item["source_type"] == "synthetic_fallback" for item in ledger["materials"])
    assert all(item["fallback_reason"] == "RuntimeError:offline-fixture" for item in ledger["materials"])
    assert all(len(item["sha256"]) == 64 for item in ledger["materials"])
    assert all(item["rights_status"] == "commercial_authorized" for item in ledger["materials"])


def test_bundled_narration_generates_real_tutorial_video_without_exposing_script_to_processor(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    service = TutorialDemoAssetService(settings)
    service._system_narration = lambda output_path, text: False  # type: ignore[method-assign]

    output = service.prepare_tutorial(tmp_path / "run")
    provenance = json.loads(output.provenance_path.read_text(encoding="utf-8"))

    assert output.video_path.is_file() and output.video_path.stat().st_size > 0
    assert provenance["narration_provider"] == "bundled_regenerable_audio"
    assert len(provenance["tutorial_video_sha256"]) == 64
    assert provenance["processing_boundary"] == "course processing receives only tutorial_video_path"
    assert "script_path" in provenance
