from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from app.adapters.ffmpeg import FfmpegAdapter
from app.config import Settings
from app.schemas.editing import CoverPlan, EditingTimeline
from app.services.caption_service import CaptionService


@dataclass(frozen=True)
class RenderArtifacts:
    preview_path: Path
    ass_path: Path
    srt_path: Path
    cover_path: Path
    report_path: Path


class RenderService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.ffmpeg = FfmpegAdapter(
            ffmpeg_bin=settings.ffmpeg_bin,
            ffprobe_bin=settings.ffprobe_bin,
        )
        self.captions = CaptionService()

    @staticmethod
    def _filter_path(path: Path) -> str:
        value = path.resolve().as_posix()
        value = value.replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")
        return value

    @staticmethod
    def _run(command: list[str]) -> None:
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode != 0:
            diagnostic = "\n".join(completed.stderr.strip().splitlines()[-12:])
            raise RuntimeError(f"FFmpeg render failed:\n{diagnostic}")

    def _build_filter(self, timeline: EditingTimeline, ass_path: Path) -> tuple[str, str, str]:
        width, height, fps = timeline.width, timeline.height, timeline.fps
        parts: list[str] = []
        concat_inputs: list[str] = []
        for index, clip in enumerate(timeline.clips):
            start = clip.source_start_seconds
            end = clip.source_end_seconds
            duration = clip.duration_seconds
            parts.extend(
                [
                    f"[{index}:v:0]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS,split=2[vbg{index}][vfg{index}]",
                    f"[vbg{index}]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},boxblur=24:2[bg{index}]",
                    f"[vfg{index}]scale={width}:{height}:force_original_aspect_ratio=decrease[fg{index}]",
                    f"[bg{index}][fg{index}]overlay=(W-w)/2:(H-h)/2,eq=contrast=1.03:saturation=1.04,setsar=1,fps={fps},format=yuv420p[v{index}]",
                ]
            )
            if clip.has_audio:
                parts.append(
                    f"[{index}:a:0]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS,aresample=48000[a{index}]"
                )
            else:
                parts.append(
                    f"anullsrc=r=48000:cl=stereo,atrim=duration={duration:.3f},asetpts=PTS-STARTPTS[a{index}]"
                )
            concat_inputs.extend([f"[v{index}]", f"[a{index}]"])

        parts.append(
            "".join(concat_inputs)
            + f"concat=n={len(timeline.clips)}:v=1:a=1[vcat][acat]"
        )
        video_label = "vcat"
        if timeline.captions:
            parts.append(f"[vcat]ass=filename='{self._filter_path(ass_path)}'[vout]")
            video_label = "vout"

        audio = timeline.audio
        original_gain = math.pow(10, audio.original_gain_db / 20)
        parts.append(f"[acat]volume={original_gain:.6f}[original]")
        next_input = len(timeline.clips)
        if audio.voiceover_path:
            voice_gain = math.pow(10, audio.voiceover_gain_db / 20)
            parts.extend(
                [
                    f"[{next_input}:a:0]atrim=duration={timeline.actual_duration_seconds:.3f},asetpts=PTS-STARTPTS,aresample=48000,volume={voice_gain:.6f},apad=whole_dur={timeline.actual_duration_seconds:.3f},atrim=duration={timeline.actual_duration_seconds:.3f}[voice]",
                    "[original][voice]amix=inputs=2:duration=longest:dropout_transition=0[program]",
                ]
            )
            next_input += 1
        else:
            parts.append("[original]anull[program]")
        if audio.bgm_path:
            bgm_index = next_input
            linear_gain = math.pow(10, audio.bgm_gain_db / 20)
            parts.extend(
                [
                    f"[{bgm_index}:a:0]atrim=duration={timeline.actual_duration_seconds:.3f},asetpts=PTS-STARTPTS,volume={linear_gain:.6f}[bgm]",
                    "[bgm][program]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[ducked]",
                    f"[program][ducked]amix=inputs=2:duration=first:dropout_transition=0,loudnorm=I={audio.target_lufs:g}:TP={audio.true_peak_db:g}:LRA=11[aout]",
                ]
            )
        else:
            parts.append(
                f"[program]loudnorm=I={audio.target_lufs:g}:TP={audio.true_peak_db:g}:LRA=11[aout]"
            )
        return ";".join(parts), video_label, "aout"

    def _render_preview(self, timeline: EditingTimeline, ass_path: Path, output: Path) -> None:
        ffmpeg = self.ffmpeg._resolve_binary(self.settings.ffmpeg_bin)
        command = [ffmpeg, "-hide_banner", "-loglevel", "error"]
        for clip in timeline.clips:
            source = self.ffmpeg._require_source(Path(clip.source_path))
            command.extend(["-i", str(source)])
        if timeline.audio.voiceover_path:
            voiceover = self.ffmpeg._require_source(Path(timeline.audio.voiceover_path))
            command.extend(["-i", str(voiceover)])
        if timeline.audio.bgm_path:
            bgm = self.ffmpeg._require_source(Path(timeline.audio.bgm_path))
            command.extend(["-stream_loop", "-1", "-i", str(bgm)])
        graph, video_label, audio_label = self._build_filter(timeline, ass_path)
        command.extend(
            [
                "-filter_complex",
                graph,
                "-map",
                f"[{video_label}]",
                "-map",
                f"[{audio_label}]",
                "-c:v",
                "libx264",
                "-preset",
                self.settings.render_preset,
                "-crf",
                str(self.settings.render_crf),
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(timeline.fps),
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                "-shortest",
                "-y",
                str(output),
            ]
        )
        self._run(command)

    def _font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        candidates = [
            self.settings.cover_font_path,
            Path("C:/Windows/Fonts/msyhbd.ttc"),
            Path("C:/Windows/Fonts/msyh.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        ]
        for candidate in candidates:
            if candidate and candidate.is_file():
                return ImageFont.truetype(str(candidate), size=size)
        return ImageFont.load_default()

    def _create_cover(self, plan: CoverPlan, output: Path, width: int, height: int) -> None:
        frame = output.with_suffix(".frame.jpg")
        self.ffmpeg.extract_frame(Path(plan.source_path), plan.source_timestamp_seconds, frame)
        with Image.open(frame) as source:
            rgb = source.convert("RGB")
            background = ImageOps.fit(rgb, (width, height), method=Image.Resampling.LANCZOS).filter(
                ImageFilter.GaussianBlur(radius=28)
            )
            background = Image.blend(background, Image.new("RGB", (width, height), "black"), 0.28)
            foreground = ImageOps.contain(rgb, (width, height), method=Image.Resampling.LANCZOS)
            background.paste(foreground, ((width - foreground.width) // 2, (height - foreground.height) // 2))
            draw = ImageDraw.Draw(background, "RGBA")
            title = plan.title.strip() or "今日精选"
            font = self._font(82)
            max_chars = 11
            lines = [title[index : index + max_chars] for index in range(0, len(title), max_chars)][:2]
            text = "\n".join(lines)
            box = draw.multiline_textbbox((0, 0), text, font=font, spacing=18, stroke_width=2)
            text_width = box[2] - box[0]
            text_height = box[3] - box[1]
            x = max(70, (width - text_width) // 2)
            y = int(height * 0.70)
            padding = 36
            draw.rounded_rectangle(
                (x - padding, y - padding, x + text_width + padding, y + text_height + padding),
                radius=26,
                fill=(0, 0, 0, 165),
            )
            draw.multiline_text(
                (x, y),
                text,
                font=font,
                fill="white",
                spacing=18,
                align="center",
                stroke_width=2,
                stroke_fill=(0, 0, 0),
            )
            background.save(output, format="JPEG", quality=94, optimize=True)
        frame.unlink(missing_ok=True)

    def render(self, timeline: EditingTimeline, output_dir: Path) -> RenderArtifacts:
        resolved_dir = output_dir.resolve()
        resolved_dir.mkdir(parents=True, exist_ok=True)
        ass_path = self.captions.write_ass(timeline.captions, resolved_dir / "captions.ass")
        srt_path = self.captions.write_srt(timeline.captions, resolved_dir / "captions.srt")
        preview_path = resolved_dir / "preview.mp4"
        cover_path = resolved_dir / "cover.jpg"
        report_path = resolved_dir / "render-report.json"

        self._render_preview(timeline, ass_path, preview_path)
        cover = timeline.cover
        if cover is None:
            first = timeline.clips[0]
            cover = CoverPlan(
                material_id=first.material_id,
                source_path=first.source_path,
                source_timestamp_seconds=(first.source_start_seconds + first.source_end_seconds) / 2,
                title=timeline.title,
            )
        self._create_cover(cover, cover_path, timeline.width, timeline.height)

        report = {
            "engine": timeline.engine,
            "canvas": {"width": timeline.width, "height": timeline.height, "fps": timeline.fps},
            "duration_seconds": timeline.actual_duration_seconds,
            "clip_count": len(timeline.clips),
            "source_count": timeline.source_count,
            "caption_count": len(timeline.captions),
            "audio": {
                "mode": timeline.audio.mode,
                "original_gain_db": timeline.audio.original_gain_db,
                "voiceover_used": bool(timeline.audio.voiceover_path),
                "voiceover_gain_db": timeline.audio.voiceover_gain_db,
                "voice_type": timeline.audio.voice_type,
                "decision_reason": timeline.audio.decision_reason,
                "target_lufs": timeline.audio.target_lufs,
                "true_peak_db": timeline.audio.true_peak_db,
                "bgm_used": bool(timeline.audio.bgm_path),
                "bgm_gain_db": timeline.audio.bgm_gain_db,
            },
            "warnings": timeline.warnings,
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return RenderArtifacts(
            preview_path=preview_path,
            ass_path=ass_path,
            srt_path=srt_path,
            cover_path=cover_path,
            report_path=report_path,
        )
