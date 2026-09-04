from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Callable
from urllib.request import Request, urlopen

from app.config import Settings


Downloader = Callable[[str, Path, int], None]


@dataclass(frozen=True)
class PreparedDemoMaterials:
    material_paths: list[Path]
    rights_ledger_path: Path


@dataclass(frozen=True)
class PreparedTutorial:
    video_path: Path
    provenance_path: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_bounded(url: str, destination: Path, maximum_bytes: int) -> None:
    request = Request(url, headers={"User-Agent": "VideoWorkbench/1.0 tutorial-demo"})
    total = 0
    with urlopen(request, timeout=30) as response, destination.open("wb") as output:
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > maximum_bytes:
            raise ValueError("demo_asset_too_large")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum_bytes:
                raise ValueError("demo_asset_too_large")
            output.write(chunk)


class TutorialDemoAssetService:
    def __init__(
        self,
        settings: Settings,
        *,
        downloader: Downloader | None = None,
        tts: object | None = None,
    ):
        self.settings = settings
        self.downloader = downloader or _download_bounded
        self.tts = tts
        self.demo_dir = Path(__file__).resolve().parents[1] / "demo"

    def _script_segments(self) -> list[dict[str, str]]:
        payload = json.loads((self.demo_dir / "tutorial-script.json").read_text(encoding="utf-8"))
        raw_segments = payload.get("segments") if isinstance(payload, dict) else None
        if not isinstance(raw_segments, list) or not raw_segments:
            raise ValueError("tutorial_demo_script_invalid")
        allowed_types = {"lecture", "software_operation", "finished_example", "intro_outro"}
        segments: list[dict[str, str]] = []
        for raw in raw_segments:
            if not isinstance(raw, dict):
                raise ValueError("tutorial_demo_script_invalid")
            segment = {
                "card": str(raw.get("card") or ""),
                "segment_type": str(raw.get("segment_type") or ""),
                "screen_label": str(raw.get("screen_label") or ""),
                "text": str(raw.get("text") or "").strip(),
            }
            if (
                not segment["text"]
                or segment["segment_type"] not in allowed_types
                or not segment["screen_label"]
            ):
                raise ValueError("tutorial_demo_script_invalid")
            segments.append(segment)
        return segments

    def _audio_duration(self, path: Path) -> float:
        completed = subprocess.run(
            [
                self.settings.ffprobe_bin,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        try:
            duration = float(completed.stdout.strip())
        except (TypeError, ValueError):
            duration = 0.0
        if completed.returncode != 0 or duration <= 0:
            raise ValueError("tutorial_demo_audio_invalid")
        return duration

    def visual_chapters(self, durations: list[float] | None = None) -> list[dict[str, object]]:
        segments = self._script_segments()
        if durations is None:
            bundled_dir = self.demo_dir / "tutorial-segments"
            durations = [
                self._audio_duration(bundled_dir / f"segment-{index:02d}.wav")
                for index in range(1, len(segments) + 1)
            ]
        if len(durations) != len(segments) or any(duration <= 0 for duration in durations):
            raise ValueError("tutorial_demo_segment_duration_invalid")
        chapters: list[dict[str, object]] = []
        cursor = 0.0
        for segment, duration in zip(segments, durations):
            end = cursor + duration
            chapters.append(
                {
                    "card": segment["card"],
                    "segment_type": segment["segment_type"],
                    "start_seconds": round(cursor, 6),
                    "end_seconds": round(end, 6),
                    "screen_label": segment["screen_label"],
                    "text": segment["text"],
                }
            )
            cursor = end
        return chapters

    def _tutorial_visual_filter(self, chapters: list[dict[str, object]]) -> str:
        filters: list[str] = []
        font_candidates = [
            self.settings.cover_font_path,
            Path("C:/Windows/Fonts/arialbd.ttf"),
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ]
        font_path = next((Path(item) for item in font_candidates if item and Path(item).is_file()), None)
        font_option = ""
        if font_path is not None:
            escaped_font_path = font_path.resolve().as_posix().replace(":", r"\:")
            font_option = f":fontfile='{escaped_font_path}'"
        colors = {
            "intro_outro": "0x24304A",
            "lecture": "0x3730A3",
            "software_operation": "0x0F766E",
            "finished_example": "0xC2410C",
        }
        for chapter in chapters:
            start = chapter["start_seconds"]
            end = chapter["end_seconds"]
            label = chapter["screen_label"]
            color = colors[str(chapter["segment_type"])]
            filters.append(
                "drawbox="
                f"x=70:y=660:w=940:h=600:color={color}@0.92:t=fill:"
                f"enable='between(t,{start},{end})'"
            )
            filters.append(
                "drawtext="
                f"text='{label}'{font_option}:fontcolor=white:fontsize=66:box=1:boxcolor=black@0.72:"
                f"boxborderw=24:x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,{start},{end})'"
            )
        return ",".join(filters)

    def load_manifest(self) -> dict[str, object]:
        manifest = json.loads(
            (self.demo_dir / "tutorial-learning-manifest.json").read_text(encoding="utf-8")
        )
        materials = manifest.get("materials")
        if not isinstance(materials, list) or len(materials) < 2:
            raise ValueError("tutorial_demo_manifest_invalid")
        required = {
            "id",
            "title",
            "file_name",
            "file_page",
            "download_url",
            "author",
            "license",
            "license_url",
            "attribution_required",
            "expected_mime_type",
            "expected_duration_seconds",
            "maximum_bytes",
        }
        for item in materials:
            if not isinstance(item, dict) or required - set(item):
                raise ValueError("tutorial_demo_manifest_invalid")
            if item["license"] not in {"CC0-1.0", "CC-BY-4.0"}:
                raise ValueError("tutorial_demo_license_not_allowed")
        return manifest

    def _probe(self, path: Path) -> dict[str, object]:
        completed = subprocess.run(
            [
                self.settings.ffprobe_bin,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            raise ValueError("demo_asset_media_invalid")
        payload = json.loads(completed.stdout)
        streams = payload.get("streams") or []
        if not any(stream.get("codec_type") == "video" for stream in streams):
            raise ValueError("demo_asset_video_stream_required")
        decoded = subprocess.run(
            [
                self.settings.ffmpeg_bin,
                "-hide_banner",
                "-loglevel",
                "error",
                "-xerror",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if decoded.returncode != 0:
            raise ValueError("demo_asset_media_decode_invalid")
        return payload

    def _synthetic_fallback(self, destination: Path, *, index: int) -> None:
        colors = ("0x6941C6", "0x0F766E", "0xC2410C")
        color = colors[index % len(colors)]
        command = [
            self.settings.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=1080x1920:r=30:d=8",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=330:sample_rate=48000:duration=8",
            "-vf",
            "drawtext=text='SYNTHETIC FALLBACK':fontcolor=white:fontsize=58:x=(w-text_w)/2:y=(h-text_h)/2",
            "-filter_threads",
            "1",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-threads",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-y",
            str(destination),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=90)
        if completed.returncode != 0 or not destination.is_file():
            command = [item for item in command]
            vf_index = command.index("-vf")
            del command[vf_index : vf_index + 2]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=90)
        if completed.returncode != 0 or not destination.is_file():
            raise RuntimeError(f"synthetic_demo_asset_failed:{completed.stderr[-240:]}")

    def prepare_materials(self, run_dir: Path) -> PreparedDemoMaterials:
        material_dir = run_dir / "materials"
        material_dir.mkdir(parents=True, exist_ok=True)
        ledger_rows: list[dict[str, object]] = []
        paths: list[Path] = []
        materials = self.load_manifest()["materials"]
        assert isinstance(materials, list)
        for index, raw in enumerate(materials):
            item = dict(raw)
            destination = material_dir / str(item["file_name"])
            source_type = "wikimedia_commons"
            fallback_reason = ""
            try:
                self.downloader(
                    str(item["download_url"]),
                    destination,
                    int(item["maximum_bytes"]),
                )
                self._probe(destination)
                digest = _sha256(destination)
                expected = str(item.get("expected_sha256") or "")
                if expected and digest != expected:
                    raise ValueError("demo_asset_checksum_mismatch")
            except Exception as error:
                destination.unlink(missing_ok=True)
                destination = material_dir / f"{item['id']}-synthetic-fallback.mp4"
                self._synthetic_fallback(destination, index=index)
                self._probe(destination)
                digest = _sha256(destination)
                source_type = "synthetic_fallback"
                fallback_reason = f"{type(error).__name__}:{error}"
            paths.append(destination.resolve())
            ledger_rows.append(
                {
                    **item,
                    "local_path": str(destination.resolve()),
                    "sha256": digest,
                    "size_bytes": destination.stat().st_size,
                    "downloaded_at": datetime.now(UTC).isoformat(),
                    "source_type": source_type,
                    "synthetic_fallback": source_type == "synthetic_fallback",
                    "fallback_reason": fallback_reason,
                    "rights_status": "commercial_authorized",
                }
            )
        ledger_path = run_dir / "rights-ledger.json"
        ledger_path.write_text(
            json.dumps({"schema_version": 1, "materials": ledger_rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return PreparedDemoMaterials(material_paths=paths, rights_ledger_path=ledger_path)

    def _prepare_aligned_narration(self, tutorial_dir: Path) -> tuple[Path, list[float]]:
        segments = self._script_segments()
        bundled_dir = self.demo_dir / "tutorial-segments"
        sources = [
            bundled_dir / f"segment-{index:02d}.wav"
            for index in range(1, len(segments) + 1)
        ]
        if any(not source.is_file() for source in sources):
            raise ValueError("tutorial_aligned_narration_unavailable")
        durations = [self._audio_duration(source) for source in sources]
        narration_path = tutorial_dir / "tutorial-narration-aligned.wav"
        command = [self.settings.ffmpeg_bin, "-hide_banner", "-loglevel", "error"]
        for source in sources:
            command.extend(["-i", str(source)])
        audio_inputs = "".join(f"[{index}:a]" for index in range(len(sources)))
        command.extend(
            [
                "-filter_complex",
                f"{audio_inputs}concat=n={len(sources)}:v=0:a=1[a]",
                "-map",
                "[a]",
                "-ar",
                "24000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                "-y",
                str(narration_path),
            ]
        )
        completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if completed.returncode != 0 or not narration_path.is_file():
            raise RuntimeError(f"tutorial_narration_concat_failed:{completed.stderr[-240:]}")
        return narration_path.resolve(), durations

    def prepare_tutorial(self, run_dir: Path) -> PreparedTutorial:
        tutorial_dir = run_dir / "tutorial"
        tutorial_dir.mkdir(parents=True, exist_ok=True)
        narration_path, segment_durations = self._prepare_aligned_narration(tutorial_dir)
        provider = "bundled_aligned_segments"
        video_path = tutorial_dir / "tutorial-learning.mp4"
        visual_chapters = self.visual_chapters(segment_durations)
        completed = subprocess.run(
            [
                self.settings.ffmpeg_bin,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=0x171923:s=1080x1920:r=30",
                "-i",
                str(narration_path),
                "-filter_threads",
                "1",
                "-vf",
                self._tutorial_visual_filter(visual_chapters),
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-threads",
                "1",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                "-y",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if completed.returncode != 0 or not video_path.is_file():
            raise RuntimeError(f"tutorial_video_generation_failed:{completed.stderr[-240:]}")
        self._probe(video_path)
        provenance = {
            "schema_version": 1,
            "narration_provider": provider,
            "tutorial_video_sha256": _sha256(video_path),
            "tutorial_video_path": str(video_path.resolve()),
            "script_path": str((self.demo_dir / "tutorial-script.json").resolve()),
            "visual_chapters": visual_chapters,
            "visual_chapters_rendered": True,
            "processing_boundary": "course processing receives only tutorial_video_path",
        }
        provenance_path = tutorial_dir / "tutorial-provenance.json"
        provenance_path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
        return PreparedTutorial(video_path=video_path.resolve(), provenance_path=provenance_path)
