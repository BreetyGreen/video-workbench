from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from app.adapters.ffmpeg import FfmpegAdapter


class PreviewService:
    def __init__(self, adapter: FfmpegAdapter, artifact_root: Path):
        self.adapter = adapter
        self.artifact_root = artifact_root.resolve()

    def generate(
        self,
        source: Path,
        task_id: str,
        *,
        max_duration_seconds: float | None = None,
    ) -> Path:
        task_dir = (self.artifact_root / task_id).resolve()
        if self.artifact_root not in task_dir.parents:
            raise ValueError("Task artifact path escapes the configured artifact root")
        task_dir.mkdir(parents=True, exist_ok=True)

        output = task_dir / "preview.mp4"
        preview = self.adapter.create_preview(
            source,
            output,
            max_duration_seconds=max_duration_seconds,
        )
        probe = self.adapter.probe_media(preview.output_path)
        quality = self.adapter.scan_quality(preview.output_path)
        report_path = task_dir / "preview.json"
        report_path.write_text(
            json.dumps(
                {
                    "preview": str(preview.output_path),
                    "probe": asdict(probe),
                    "quality": {
                        "black_frame_warnings": quality.black_frame_warnings,
                        "silence_warnings": quality.silence_warnings,
                    },
                    "commands": [preview.command, quality.command],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return report_path
