from __future__ import annotations

import json
from pathlib import Path
import zipfile

from app.services.jianying_handoff_service import JianyingHandoffService
from app.services.jianying_runtime_service import JianyingRuntimeService


def _write_manifest(data_dir: Path, draft_root: Path) -> None:
    runtime = data_dir / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "jianying.json").write_text(
        json.dumps(
            {
                "platform": "Windows",
                "installed": True,
                "app_path": "B:\\Apps\\JianyingPro\\JianyingPro.exe",
                "draft_root": "B:\\JianyingData\\Drafts\\JianyingPro Drafts",
                "container_draft_root": str(draft_root),
                "draft_root_writable": True,
                "checked_at": "2026-08-31T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )


def _write_package(artifact_dir: Path, task_id: str, *, unsafe: bool = False) -> Path:
    task_dir = artifact_dir / task_id
    task_dir.mkdir(parents=True)
    top = "帽子商品草稿"
    package = task_dir / "draft.zip"
    source_prefix = f"/data/artifacts/{task_id}/drafts/{top}"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            f"{top}/draft_info.json",
            json.dumps(
                {
                    "materials": {
                        "videos": [{"path": f"{source_prefix}/assets/hat.mp4"}]
                    }
                },
                ensure_ascii=False,
            ),
        )
        archive.writestr(f"{top}/draft_content.json", "{}")
        archive.writestr(f"{top}/draft_meta_info.json", "{}")
        archive.writestr(f"{top}/assets/hat.mp4", b"video")
        if unsafe:
            archive.writestr("../escape.txt", "bad")
    (task_dir / "quality-report.json").write_text(
        json.dumps({"status": "pass", "blocking_failures": []}),
        encoding="utf-8",
    )
    (task_dir / "review.json").write_text(
        json.dumps({"warnings": ["尚未在本机剪映打开草稿，兼容性状态待人工确认。"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return package


def test_runtime_manifest_wins_over_container_platform(tmp_path: Path):
    data_dir = tmp_path / "data"
    draft_root = tmp_path / "drafts"
    draft_root.mkdir()
    _write_manifest(data_dir, draft_root)

    snapshot = JianyingRuntimeService(data_dir).snapshot()

    assert snapshot["platform"] == "Windows"
    assert snapshot["installed"] is True
    assert snapshot["ready_for_auto_import"] is True
    assert snapshot["container_draft_root"] == str(draft_root)


def test_imports_rewrites_and_is_idempotent(tmp_path: Path):
    data_dir = tmp_path / "data"
    artifact_dir = data_dir / "artifacts"
    draft_root = tmp_path / "drafts"
    draft_root.mkdir()
    task_id = "d7c38c99-d7b3-4e0e-99ed-9be1444fbe2f"
    _write_manifest(data_dir, draft_root)
    _write_package(artifact_dir, task_id)
    service = JianyingHandoffService(data_dir, artifact_dir, JianyingRuntimeService(data_dir))

    first = service.import_task(task_id)
    second = service.import_task(task_id)

    assert first["status"] == "imported"
    assert second["status"] == "imported"
    assert second["idempotent"] is True
    assert first["draft_path"] == second["draft_path"]
    assert Path(first["container_draft_path"]).is_dir()
    draft_info = json.loads((Path(first["container_draft_path"]) / "draft_info.json").read_text(encoding="utf-8"))
    assert draft_info["materials"]["videos"][0]["path"].startswith("B:\\JianyingData")
    request = data_dir / "runtime" / "open-requests" / f"{task_id}.json"
    assert request.is_file()
    review = json.loads((artifact_dir / task_id / "review.json").read_text(encoding="utf-8"))
    assert all("尚未在本机剪映打开草稿" not in item for item in review["warnings"])
    assert any("已自动导入" in item for item in review["warnings"])


def test_rejects_zip_slip(tmp_path: Path):
    data_dir = tmp_path / "data"
    artifact_dir = data_dir / "artifacts"
    draft_root = tmp_path / "drafts"
    draft_root.mkdir()
    task_id = "d7c38c99-d7b3-4e0e-99ed-9be1444fbe2f"
    _write_manifest(data_dir, draft_root)
    _write_package(artifact_dir, task_id, unsafe=True)
    service = JianyingHandoffService(data_dir, artifact_dir, JianyingRuntimeService(data_dir))

    result = service.import_task(task_id)

    assert result["status"] == "failed"
    assert result["code"] == "unsafe_archive_path"
    assert not (tmp_path / "escape.txt").exists()
