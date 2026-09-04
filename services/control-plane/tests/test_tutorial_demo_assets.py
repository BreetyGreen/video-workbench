from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.tutorial_demo_assets import TutorialDemoAssetService


def test_tutorial_demo_visual_chapters_cover_mixed_teaching_content(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    service = TutorialDemoAssetService(settings)

    chapters = service.visual_chapters()

    assert {chapter["segment_type"] for chapter in chapters} >= {
        "lecture",
        "software_operation",
        "finished_example",
    }
    assert all(chapter["start_seconds"] < chapter["end_seconds"] for chapter in chapters)
    operation = next(item for item in chapters if item["segment_type"] == "software_operation")
    example = next(item for item in chapters if item["segment_type"] == "finished_example")
    assert "CAPCUT" in operation["screen_label"]
    assert "FINAL CUT" in example["screen_label"]
    assert operation["text"] == "现在进入剪映操作，把素材拖到时间线，再点击分割并调整顺序。"
    assert example["text"] == "下面播放完整成片示例。"
    assert all(
        abs(float(left["end_seconds"]) - float(right["start_seconds"])) < 0.001
        for left, right in zip(chapters, chapters[1:])
    )


def test_demo_probe_rejects_container_that_cannot_be_fully_decoded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "damaged.webm"
    source.write_bytes(b"container-header-but-broken-frames")
    calls = iter(
        [
            SimpleNamespace(
                returncode=0,
                stdout='{"streams":[{"codec_type":"video"}],"format":{"duration":"8"}}',
                stderr="",
            ),
            SimpleNamespace(returncode=1, stdout="", stderr="Invalid data found when processing input"),
        ]
    )
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        commands.append(command)
        return next(calls)

    monkeypatch.setattr("app.services.tutorial_demo_assets.subprocess.run", fake_run)

    with pytest.raises(ValueError, match="demo_asset_media_decode_invalid"):
        TutorialDemoAssetService(Settings(data_dir=tmp_path / "data"))._probe(source)

    assert "-xerror" in commands[1]
    assert "0:v:0" in commands[1]
    assert "0:a?" in commands[1]


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


def test_aligned_segment_narration_generates_real_tutorial_video_without_exposing_script_to_processor(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    service = TutorialDemoAssetService(settings)

    output = service.prepare_tutorial(tmp_path / "run")
    provenance = json.loads(output.provenance_path.read_text(encoding="utf-8"))

    assert output.video_path.is_file() and output.video_path.stat().st_size > 0
    assert provenance["narration_provider"] == "bundled_aligned_segments"
    assert len(provenance["tutorial_video_sha256"]) == 64
    assert provenance["visual_chapters_rendered"] is True
    assert {item["segment_type"] for item in provenance["visual_chapters"]} >= {
        "lecture",
        "software_operation",
        "finished_example",
    }
    assert provenance["processing_boundary"] == "course processing receives only tutorial_video_path"
    assert "script_path" in provenance
    operation = next(item for item in provenance["visual_chapters"] if item["segment_type"] == "software_operation")
    example = next(item for item in provenance["visual_chapters"] if item["segment_type"] == "finished_example")
    assert operation["text"].startswith("现在进入剪映操作")
    assert example["text"].startswith("下面播放完整成片示例")
