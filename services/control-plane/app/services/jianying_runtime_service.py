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
            current_platform = platform.system()
            manifest_platform = str(manifest.get("platform") or "")
            host_root_value = str(manifest.get("draft_root") or "")
            container_root_value = str(manifest.get("container_draft_root") or "")
            native_runtime = bool(
                host_root_value
                and manifest_platform.casefold() == current_platform.casefold()
            )
            effective_root_value = host_root_value if native_runtime else container_root_value
            effective_root = Path(effective_root_value) if effective_root_value else None
            installed = bool(manifest.get("installed"))
            writable = bool(
                manifest.get("draft_root_writable")
                and effective_root is not None
                and effective_root.is_dir()
            )
            return {
                **manifest,
                "installed": installed,
                "container_draft_root": str(effective_root) if effective_root else None,
                "ready_for_auto_import": installed and writable and bool(host_root_value),
                "needs_user_action": not (installed and writable and bool(host_root_value)),
                "source": "host_manifest_native" if native_runtime else "host_manifest",
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
