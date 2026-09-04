from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
from sqlmodel import Session, select

from app.adapters.ffmpeg import FfmpegAdapter
from app.config import Settings
from app.models import CourseAsset, CourseAssetRole, MaterialShot


def _average_hash(path: Path) -> str:
    with Image.open(path) as image:
        pixels = list(image.convert("L").resize((8, 8)).get_flattened_data())
    average = sum(pixels) / len(pixels)
    bits = "".join("1" if value >= average else "0" for value in pixels)
    return f"{int(bits, 2):016x}"


class CourseMaterialAnalysisService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.ffmpeg = FfmpegAdapter(
            ffmpeg_bin=settings.ffmpeg_bin,
            ffprobe_bin=settings.ffprobe_bin,
        )

    def analyze_asset(self, session: Session, asset_id: str) -> list[MaterialShot]:
        existing = list(
            session.exec(
                select(MaterialShot)
                .where(MaterialShot.asset_id == asset_id)
                .order_by(MaterialShot.start_ms)
            ).all()
        )
        if existing:
            return existing
        asset = session.get(CourseAsset, asset_id)
        if asset is None:
            raise ValueError("course_asset_not_found")
        if asset.role != CourseAssetRole.MATERIAL or not asset.mime_type.startswith("video/"):
            raise ValueError("video_material_required")

        source = Path(asset.stored_path).resolve()
        probe = self.ffmpeg.probe_media(source)
        scenes = self.ffmpeg.detect_scenes(source, threshold=self.settings.scene_threshold)
        if not scenes:
            raise ValueError("material_scenes_not_detected")
        output_dir = (self.settings.data_dir / "course-analysis" / asset.id / "shots").resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        tags = ["vertical" if (probe.height or 0) > (probe.width or 0) else "landscape"]
        if probe.audio_streams:
            tags.append("has_audio")

        shots: list[MaterialShot] = []
        for index, scene in enumerate(scenes):
            start_ms = int(scene.start_seconds * 1000)
            end_ms = int(scene.end_seconds * 1000)
            if end_ms <= start_ms:
                continue
            timestamp = scene.start_seconds + (scene.end_seconds - scene.start_seconds) / 2
            thumbnail = self.ffmpeg.extract_frame(
                source,
                timestamp,
                output_dir / f"shot-{index:04d}.jpg",
            )
            shots.append(
                MaterialShot(
                    asset_id=asset.id,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    thumbnail_path=str(thumbnail),
                    tags_json=json.dumps(tags, ensure_ascii=False),
                    phash=_average_hash(thumbnail),
                )
            )
        session.add_all(shots)
        session.commit()
        for shot in shots:
            session.refresh(shot)
        return shots
