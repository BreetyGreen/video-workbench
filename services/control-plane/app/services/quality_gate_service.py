from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.adapters.ffmpeg import FfmpegAdapter
from app.config import Settings
from app.schemas.editing import EditingTimeline, MediaAnalysis


class QualityGate(BaseModel):
    name: str = Field(min_length=1)
    status: Literal["pass", "warn", "fail"]
    blocking: bool
    message: str = Field(min_length=1)
    evidence: dict[str, object] = Field(default_factory=dict)


class QualityReport(BaseModel):
    status: Literal["pass", "warn", "fail"]
    gates: list[QualityGate]
    blocking_failures: list[str] = Field(default_factory=list)


class QualityGateService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.ffmpeg = FfmpegAdapter(
            ffmpeg_bin=settings.ffmpeg_bin,
            ffprobe_bin=settings.ffprobe_bin,
        )

    @staticmethod
    def _gate(
        name: str,
        passed: bool,
        *,
        message: str,
        evidence: dict[str, object] | None = None,
        blocking: bool = True,
    ) -> QualityGate:
        return QualityGate(
            name=name,
            status="pass" if passed else ("fail" if blocking else "warn"),
            blocking=blocking,
            message=message,
            evidence=evidence or {},
        )

    def evaluate(
        self,
        *,
        preview_path: Path,
        timeline: EditingTimeline,
        analyses: list[MediaAnalysis],
        captions_path: Path,
        draft_path: Path,
        cover_path: Path,
    ) -> QualityReport:
        required = {
            "preview.mp4": preview_path,
            "captions.srt": captions_path,
            "draft.zip": draft_path,
            "cover.jpg": cover_path,
        }
        missing = [name for name, path in required.items() if not path.is_file()]
        gates = [
            self._gate(
                "required_artifacts",
                not missing,
                message="交付物完整" if not missing else "缺少交付物",
                evidence={"missing": missing},
            )
        ]
        if not preview_path.is_file():
            blocking = [gate.name for gate in gates if gate.status == "fail" and gate.blocking]
            return QualityReport(status="fail", gates=gates, blocking_failures=blocking)

        try:
            probe = self.ffmpeg.probe_media(preview_path)
        except Exception as error:
            gates.append(
                self._gate(
                    "playable_media",
                    False,
                    message="成片无法解析",
                    evidence={"error": type(error).__name__},
                )
            )
            blocking = [gate.name for gate in gates if gate.status == "fail" and gate.blocking]
            return QualityReport(status="fail", gates=gates, blocking_failures=blocking)

        playable = probe.video_streams > 0 and probe.audio_streams > 0 and probe.duration_seconds > 0
        gates.append(
            self._gate(
                "playable_media",
                playable,
                message="视频和音频轨可播放" if playable else "缺少有效视频或音频轨",
                evidence={
                    "video_streams": probe.video_streams,
                    "audio_streams": probe.audio_streams,
                    "video_codec": probe.video_codec or "",
                    "audio_codec": probe.audio_codec or "",
                },
            )
        )
        canvas_ok = probe.width == timeline.width and probe.height == timeline.height
        gates.append(
            self._gate(
                "canvas",
                canvas_ok,
                message="画布符合竖屏交付规格" if canvas_ok else "画布尺寸不符合时间线",
                evidence={
                    "expected": f"{timeline.width}x{timeline.height}",
                    "actual": f"{probe.width}x{probe.height}",
                },
            )
        )
        drift = abs(probe.duration_seconds - timeline.actual_duration_seconds)
        gates.append(
            self._gate(
                "duration",
                drift <= self.settings.quality_duration_tolerance_seconds,
                message="成片时长与时间线一致" if drift <= self.settings.quality_duration_tolerance_seconds else "成片时长漂移",
                evidence={
                    "timeline_seconds": timeline.actual_duration_seconds,
                    "render_seconds": probe.duration_seconds,
                    "drift_seconds": round(drift, 3),
                },
            )
        )
        contiguous = bool(timeline.clips) and abs(timeline.clips[0].timeline_start_seconds) <= 0.02
        cursor = 0.0
        for clip in timeline.clips:
            contiguous = contiguous and abs(clip.timeline_start_seconds - cursor) <= 0.02
            cursor = clip.timeline_end_seconds
        contiguous = contiguous and abs(cursor - timeline.actual_duration_seconds) <= 0.02
        gates.append(
            self._gate(
                "timeline_continuity",
                contiguous,
                message="时间线连续无空洞" if contiguous else "时间线存在空洞或时长不一致",
            )
        )
        hook_ok = bool(timeline.clips) and timeline.clips[0].timeline_start_seconds <= 0.02 and timeline.clips[0].reason.startswith("hook:")
        gates.append(
            self._gate(
                "hook_placement",
                hook_ok,
                message="钩子从首帧开始" if hook_ok else "首镜头未标记为钩子",
            )
        )

        try:
            scan = self.ffmpeg.scan_quality(preview_path)
            black_durations = [
                float(match.group(1))
                for line in scan.black_frame_warnings
                for match in [re.search(r"black_duration:([0-9.]+)", line)]
                if match
            ]
            max_black = max(black_durations, default=0)
            gates.append(
                self._gate(
                    "black_frames",
                    max_black <= self.settings.quality_max_black_seconds,
                    message="未发现超限黑场" if max_black <= self.settings.quality_max_black_seconds else "发现超限黑场",
                    evidence={"max_black_seconds": max_black},
                )
            )
        except Exception as error:
            gates.append(
                self._gate(
                    "black_frames",
                    False,
                    message="黑场检测未完成",
                    evidence={"error": type(error).__name__},
                )
            )

        try:
            silences = self.ffmpeg.detect_silence(
                preview_path,
                threshold_db=self.settings.silence_threshold_db,
                minimum_seconds=min(0.5, self.settings.quality_max_silence_seconds),
            )
            max_silence = max(
                (item.end_seconds - item.start_seconds for item in silences),
                default=0,
            )
            gates.append(
                self._gate(
                    "long_silence",
                    max_silence <= self.settings.quality_max_silence_seconds,
                    message="未发现超限静音" if max_silence <= self.settings.quality_max_silence_seconds else "发现超限静音",
                    evidence={"max_silence_seconds": round(max_silence, 3)},
                )
            )
        except Exception as error:
            gates.append(
                self._gate(
                    "long_silence",
                    False,
                    message="静音检测未完成",
                    evidence={"error": type(error).__name__},
                )
            )

        speech_segments = sum(len(item.transcript.segments) for item in analyses)
        captions_ok = speech_segments == 0 or (
            captions_path.is_file() and bool(captions_path.read_text(encoding="utf-8").strip())
        )
        gates.append(
            self._gate(
                "captions",
                captions_ok,
                message="字幕覆盖要求已满足" if captions_ok else "检测到语音但字幕为空",
                evidence={"speech_segments": speech_segments},
            )
        )
        if timeline.audio.voiceover_path:
            voiceover_overrun = max(
                0.0,
                timeline.audio.voiceover_duration_seconds - timeline.actual_duration_seconds,
            )
            voiceover_fits = voiceover_overrun <= self.settings.quality_duration_tolerance_seconds
            gates.append(
                self._gate(
                    "voiceover_fit",
                    voiceover_fits,
                    message="旁白时长适配成片" if voiceover_fits else "旁白超出成片，末尾会被截断",
                    evidence={
                        "timeline_seconds": round(timeline.actual_duration_seconds, 3),
                        "voiceover_seconds": round(timeline.audio.voiceover_duration_seconds, 3),
                        "overrun_seconds": round(voiceover_overrun, 3),
                    },
                )
            )
            intervals = sorted(
                (max(0.0, cue.start_seconds), min(timeline.actual_duration_seconds, cue.end_seconds))
                for cue in timeline.captions
                if cue.end_seconds > cue.start_seconds
            )
            covered = 0.0
            current_start = current_end = None
            for start, end in intervals:
                if current_start is None:
                    current_start, current_end = start, end
                elif start <= current_end + 0.02:
                    current_end = max(current_end, end)
                else:
                    covered += current_end - current_start
                    current_start, current_end = start, end
            if current_start is not None:
                covered += current_end - current_start
            coverage = covered / max(0.001, timeline.actual_duration_seconds)
            narration_ok = coverage >= 0.85
            gates.append(
                self._gate(
                    "narration_coverage",
                    narration_ok,
                    message="旁白字幕覆盖完整" if narration_ok else "旁白或字幕只覆盖了部分成片",
                    evidence={
                        "covered_seconds": round(covered, 3),
                        "timeline_seconds": round(timeline.actual_duration_seconds, 3),
                        "voiceover_seconds": round(timeline.audio.voiceover_duration_seconds, 3),
                        "coverage_percent": round(coverage * 100, 1),
                    },
                )
            )
        preview_grade = any(
            item.transcript.quality_profile == "fast_preview"
            or item.transcript.model in {"tiny", "base", "small"}
            or bool(item.transcript.fallback_reason)
            for item in analyses
            if item.transcript.segments
        )
        gates.append(
            self._gate(
                "transcription_grade",
                not preview_grade,
                message="转写使用生产级路径" if not preview_grade else "转写使用预览或回退路径，建议人工抽检字幕",
                blocking=False,
            )
        )
        blocking = [gate.name for gate in gates if gate.status == "fail" and gate.blocking]
        status = "fail" if blocking else "warn" if any(gate.status == "warn" for gate in gates) else "pass"
        return QualityReport(status=status, gates=gates, blocking_failures=blocking)

    @staticmethod
    def write(report: QualityReport, path: Path) -> Path:
        resolved = path.resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return resolved
