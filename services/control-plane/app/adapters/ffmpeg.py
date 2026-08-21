from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

from app.schemas.editing import FrameEvidence, SceneInterval, SilenceInterval


class MediaToolNotFoundError(RuntimeError):
    """Raised when FFmpeg or FFprobe cannot be resolved."""


@dataclass(frozen=True)
class MediaProbe:
    duration_seconds: float
    video_streams: int
    audio_streams: int
    width: int | None
    height: int | None
    video_codec: str | None
    audio_codec: str | None


@dataclass(frozen=True)
class PreviewResult:
    output_path: Path
    command: list[str]


@dataclass(frozen=True)
class QualityReport:
    black_frame_warnings: list[str]
    silence_warnings: list[str]
    command: list[str]


class FfmpegAdapter:
    def __init__(self, *, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe"):
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin

    @staticmethod
    def _resolve_binary(command: str) -> str:
        candidate = Path(command)
        if candidate.is_file():
            return str(candidate.resolve())
        resolved = shutil.which(command)
        if resolved:
            return resolved
        raise MediaToolNotFoundError(f"Media tool not found: {command}")

    @staticmethod
    def _require_source(source: Path) -> Path:
        resolved = source.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Media source does not exist: {resolved}")
        return resolved

    def probe_media(self, source: Path) -> MediaProbe:
        ffprobe = self._resolve_binary(self.ffprobe_bin)
        resolved_source = self._require_source(source)
        command = [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,duration",
            "-of",
            "json",
            str(resolved_source),
        ]
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        streams = payload.get("streams", [])
        video = next((item for item in streams if item.get("codec_type") == "video"), None)
        audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
        raw_duration = float(
            (video or {}).get("duration") or payload.get("format", {}).get("duration", 0)
        )
        return MediaProbe(
            # pyJianYingDraft/MediaInfo exposes source duration in whole milliseconds.
            # Floor here so every planned source range is legal in both renderers.
            duration_seconds=math.floor(raw_duration * 1000) / 1000,
            video_streams=sum(item.get("codec_type") == "video" for item in streams),
            audio_streams=sum(item.get("codec_type") == "audio" for item in streams),
            width=video.get("width") if video else None,
            height=video.get("height") if video else None,
            video_codec=video.get("codec_name") if video else None,
            audio_codec=audio.get("codec_name") if audio else None,
        )

    def create_preview(
        self,
        source: Path,
        output: Path,
        *,
        max_duration_seconds: float | None = None,
    ) -> PreviewResult:
        ffmpeg = self._resolve_binary(self.ffmpeg_bin)
        resolved_source = self._require_source(source)
        resolved_output = output.resolve()
        resolved_output.parent.mkdir(parents=True, exist_ok=True)
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(resolved_source),
        ]
        if max_duration_seconds is not None:
            command.extend(["-t", f"{max(0.001, max_duration_seconds):.3f}"])
        command.extend(
            [
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=decrease,"
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-y",
            str(resolved_output),
            ]
        )
        subprocess.run(command, check=True, capture_output=True, text=True)
        return PreviewResult(output_path=resolved_output, command=command)

    def scan_quality(self, source: Path) -> QualityReport:
        ffmpeg = self._resolve_binary(self.ffmpeg_bin)
        resolved_source = self._require_source(source)
        command = [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(resolved_source),
            "-vf",
            "blackdetect=d=0.5:pix_th=0.10",
            "-af",
            "silencedetect=n=-50dB:d=0.5",
            "-f",
            "null",
            os.devnull,
        ]
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        diagnostic_lines = completed.stderr.splitlines()
        return QualityReport(
            black_frame_warnings=[line.strip() for line in diagnostic_lines if "black_start:" in line],
            silence_warnings=[line.strip() for line in diagnostic_lines if "silence_start:" in line],
            command=command,
        )

    def detect_silence(
        self,
        source: Path,
        *,
        threshold_db: float = -42.0,
        minimum_seconds: float = 0.8,
    ) -> list[SilenceInterval]:
        if self.probe_media(source).audio_streams == 0:
            return []
        ffmpeg = self._resolve_binary(self.ffmpeg_bin)
        resolved_source = self._require_source(source)
        command = [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(resolved_source),
            "-af",
            f"silencedetect=noise={threshold_db:g}dB:d={minimum_seconds:g}",
            "-f",
            "null",
            os.devnull,
        ]
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        starts: list[float] = []
        intervals: list[SilenceInterval] = []
        for line in completed.stderr.splitlines():
            start_match = re.search(r"silence_start:\s*([0-9.]+)", line)
            if start_match:
                starts.append(float(start_match.group(1)))
            end_match = re.search(r"silence_end:\s*([0-9.]+)", line)
            if end_match and starts:
                start = starts.pop(0)
                end = float(end_match.group(1))
                if end > start:
                    intervals.append(SilenceInterval(start_seconds=start, end_seconds=end))
        duration = self.probe_media(source).duration_seconds
        for start in starts:
            if duration > start:
                intervals.append(SilenceInterval(start_seconds=start, end_seconds=duration))
        return intervals

    def detect_scenes(
        self,
        source: Path,
        *,
        threshold: float = 0.25,
    ) -> list[SceneInterval]:
        ffmpeg = self._resolve_binary(self.ffmpeg_bin)
        resolved_source = self._require_source(source)
        probe = self.probe_media(source)
        command = [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(resolved_source),
            "-vf",
            f"select=gt(scene\\,{threshold:g}),showinfo",
            "-an",
            "-f",
            "null",
            os.devnull,
        ]
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        cuts = [
            float(match.group(1))
            for match in re.finditer(r"pts_time:([0-9.]+)", completed.stderr)
        ]
        boundaries = sorted(
            set([0.0, *[cut for cut in cuts if 0 < cut < probe.duration_seconds], probe.duration_seconds])
        )
        return [
            SceneInterval(
                start_seconds=start,
                end_seconds=end,
                score=threshold if start > 0 else 0,
            )
            for start, end in zip(boundaries, boundaries[1:])
            if end - start >= 0.05
        ]

    def extract_frame(self, source: Path, timestamp_seconds: float, output: Path) -> Path:
        ffmpeg = self._resolve_binary(self.ffmpeg_bin)
        resolved_source = self._require_source(source)
        resolved_output = output.resolve()
        resolved_output.parent.mkdir(parents=True, exist_ok=True)
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{max(0, timestamp_seconds):.3f}",
            "-i",
            str(resolved_source),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            "-y",
            str(resolved_output),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
        if not resolved_output.is_file():
            raise RuntimeError(f"FFmpeg did not create frame: {resolved_output}")
        return resolved_output

    @staticmethod
    def measure_frame(frame_path: Path, *, timestamp_seconds: float) -> FrameEvidence:
        resolved = frame_path.resolve()
        with Image.open(resolved) as image:
            rgb = image.convert("RGB")
            gray = rgb.convert("L")
            gray_stats = ImageStat.Stat(gray)
            edge_stats = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES))
            return FrameEvidence(
                timestamp_seconds=max(0, timestamp_seconds),
                image_path=str(resolved),
                width=rgb.width,
                height=rgb.height,
                brightness=float(gray_stats.mean[0]),
                contrast=float(gray_stats.stddev[0]),
                sharpness=float(edge_stats.var[0]),
            )
