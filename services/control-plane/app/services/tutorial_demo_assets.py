from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
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
            "-c:v",
            "libx264",
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

    def _tutorial_text(self) -> str:
        payload = json.loads((self.demo_dir / "tutorial-script.json").read_text(encoding="utf-8"))
        return "\n".join(str(item["text"]) for item in payload["segments"])

    def _system_narration(self, output_path: Path, text: str) -> bool:
        if shutil.which("say"):
            completed = subprocess.run(
                ["say", "-v", "Tingting", "-o", str(output_path), text],
                capture_output=True,
                timeout=120,
            )
            return completed.returncode == 0 and output_path.is_file()
        if shutil.which("powershell"):
            escaped_output = str(output_path).replace("'", "''")
            escaped_text = text.replace("'", "''")
            script = (
                "Add-Type -AssemblyName System.Speech; "
                "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$s.SetOutputToWaveFile('{escaped_output}'); $s.Speak('{escaped_text}'); $s.Dispose()"
            )
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                timeout=120,
            )
            return completed.returncode == 0 and output_path.is_file()
        return False

    def prepare_tutorial(self, run_dir: Path) -> PreparedTutorial:
        tutorial_dir = run_dir / "tutorial"
        tutorial_dir.mkdir(parents=True, exist_ok=True)
        text = self._tutorial_text()
        narration_path = tutorial_dir / "tutorial-narration.wav"
        provider = ""
        if self.tts is not None and bool(getattr(self.tts, "configured", False)):
            try:
                result = self.tts.synthesize(text, tutorial_dir / "tutorial-narration.mp3")
                narration_path = Path(result.path)
                provider = "configured_tts"
            except Exception:
                provider = ""
        if not provider and self._system_narration(narration_path, text):
            provider = "system_speech"
        if not provider:
            bundled = self.demo_dir / "tutorial-narration.mp3"
            if not bundled.is_file():
                raise ValueError("tutorial_narration_unavailable")
            narration_path = tutorial_dir / bundled.name
            shutil.copy2(bundled, narration_path)
            provider = "bundled_regenerable_audio"
        video_path = tutorial_dir / "tutorial-learning.mp4"
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
                "-vf",
                "drawtext=text='VIDEO WORKBENCH  COURSE LEARNING':fontcolor=white:fontsize=42:x=(w-text_w)/2:y=h*0.45",
                "-c:v",
                "libx264",
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
        if completed.returncode != 0:
            fallback_command = [
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
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                "-y",
                str(video_path),
            ]
            completed = subprocess.run(
                fallback_command,
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
            "processing_boundary": "course processing receives only tutorial_video_path",
        }
        provenance_path = tutorial_dir / "tutorial-provenance.json"
        provenance_path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
        return PreparedTutorial(video_path=video_path.resolve(), provenance_path=provenance_path)
