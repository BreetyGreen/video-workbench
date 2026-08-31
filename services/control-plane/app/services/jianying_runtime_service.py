from __future__ import annotations

import json
from pathlib import Path
import platform
from typing import Any

from app.platforms.jianying import discover_jianying


class JianyingRuntimeService:
    """Resolve Jianying from a native-launcher manifest before container fallbacks."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.manifest_path = self.data_dir / "runtime" / "jianying.json"

    def snapshot(self) -> dict[str, Any]:
        manifest = self._read_manifest()
        if manifest is not None:
            container_root = Path(str(manifest.get("container_draft_root") or ""))
            installed = bool(manifest.get("installed"))
            writable = bool(manifest.get("draft_root_writable")) and container_root.is_dir()
            return {
                **manifest,
                "installed": installed,
                "container_draft_root": str(container_root) if str(container_root) else None,
                "ready_for_auto_import": installed and writable and bool(manifest.get("draft_root")),
                "needs_user_action": not (installed and writable and bool(manifest.get("draft_root"))),
                "source": "host_manifest",
            }

        system = platform.system()
        location = discover_jianying(home=Path.home(), system=system)
        return {
            "platform": system,
            "installed": location.installed,
            "app_path": str(location.app_path) if location.app_path else None,
            "draft_root": str(location.draft_root) if location.draft_root else None,
            "container_draft_root": str(location.draft_root) if location.draft_root else None,
            "draft_root_writable": bool(location.draft_root and location.draft_root.is_dir()),
            "ready_for_auto_import": bool(location.installed and location.draft_root),
            "needs_user_action": not bool(location.installed and location.draft_root),
            "source": "process_fallback",
        }

    def _read_manifest(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None
