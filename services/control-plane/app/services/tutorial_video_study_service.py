"""Study a tutorial video end to end with a vision model, chunk by chunk.

Each chunk (default 120 s) is transcoded to a small MP4, sent as a base64
``video_url`` together with the matching transcript lines, and the model returns
structured notes: what the teacher said, what they did in the editor, and
reusable rules with quotes and timecodes. Chunk results are persisted so a
rerun resumes instead of paying again; failures are recorded, never invented.
"""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.adapters.ffmpeg import FfmpegAdapter
from app.config import Settings
from app.schemas.editing import TranscriptResult
from app.schemas.tutorial_study import LessonStudy, LessonStudyRule, LessonStudySegment, StudyChunkReply

STUDY_PROMPT = (
    "你是剪辑教学分析师。下面是一节剪辑教学视频的一段（视频从本段第0秒开始计时）和同一段的老师口述转写。"
    "请逐段记录老师讲了什么、在软件里做了什么操作、哪些是可复用的剪辑规则。只输出一个JSON对象："
    '{"segments":[{"start":秒,"end":秒,"type":"lecture|software_operation|finished_example|intro_outro|other","summary":"...",'
    '"teacher_actions":["在剪辑软件中的具体操作，含界面位置和参数"],'
    '"rules":[{"category":"hook|pacing|structure|captions|audio|cta|negative|closeup|comparison",'
    '"instruction":"可执行规则","evidence_quote":"老师原话","start":秒,"end":秒}]}],"uncertain":["看不清或没把握的地方"]}。'
    "规则必须来自老师明确讲解或演示，示例广告里的商品口播不是规则；不要编造画面里没有的操作；看不清就写进uncertain。"
)


@dataclass(frozen=True)
class ChunkPlan:
    index: int
    start_seconds: float
    end_seconds: float


class TutorialVideoStudyService:
    def __init__(self, settings: Settings, director: Any | None):
        self.settings = settings
        self.director = director
        self.ffmpeg = FfmpegAdapter(ffmpeg_bin=settings.ffmpeg_bin, ffprobe_bin=settings.ffprobe_bin)

    @property
    def configured(self) -> bool:
        return bool(self.settings.tutorial_study_enabled and self.director is not None
                    and getattr(self.director, "configured", False))

    @property
    def model(self) -> str:
        return self.settings.tutorial_study_model or getattr(self.director, "model", "")

    # ---- planning -----------------------------------------------------------
    def plan(self, duration_seconds: float) -> list[ChunkPlan]:
        chunk = max(20, int(self.settings.tutorial_study_chunk_seconds))
        plans: list[ChunkPlan] = []
        start = 0.0
        index = 0
        while start < duration_seconds - 0.5:
            end = min(duration_seconds, start + chunk)
            plans.append(ChunkPlan(index=index, start_seconds=start, end_seconds=end))
            start = end
            index += 1
        return plans

    # ---- transcoding --------------------------------------------------------
    def _transcode(self, source: Path, plan: ChunkPlan, target: Path) -> Path:
        ffmpeg = self.ffmpeg._resolve_binary(self.settings.ffmpeg_bin)
        for crf, long_side in ((30, 640), (34, 480), (38, 360)):
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{plan.start_seconds:.3f}",
                       "-t", f"{plan.end_seconds - plan.start_seconds:.3f}", "-i", str(source),
                       "-vf", f"scale='if(gt(iw,ih),{long_side},-2)':'if(gt(iw,ih),-2,{long_side})'",
                       "-r", "2", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
                       "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target)]
            completed = subprocess.run(command, capture_output=True, text=True)
            if completed.returncode != 0:
                raise RuntimeError("chunk_transcode_failed:" + "\n".join(completed.stderr.strip().splitlines()[-5:]))
            if target.stat().st_size <= self.settings.tutorial_study_max_chunk_bytes:
                return target
        raise RuntimeError("chunk_too_large_after_transcode")

    @staticmethod
    def _transcript_lines(transcript: TranscriptResult, plan: ChunkPlan) -> str:
        lines = []
        for segment in transcript.segments:
            if segment.end_seconds < plan.start_seconds or segment.start_seconds > plan.end_seconds:
                continue
            lines.append(f"[{segment.start_seconds - plan.start_seconds:.1f}-{segment.end_seconds - plan.start_seconds:.1f}] "
                         f"{segment.text.strip()}")
        return "\n".join(lines) if lines else "（本段没有识别到口述）"

    # ---- one chunk ----------------------------------------------------------
    def _study_chunk(self, source: Path, transcript: TranscriptResult, plan: ChunkPlan, work_dir: Path) -> dict:
        result_path = work_dir / f"chunk-{plan.index:04d}.json"
        if result_path.is_file():
            try:
                cached = json.loads(result_path.read_text(encoding="utf-8"))
                if cached.get("status") == "ok":
                    return cached
            except (OSError, ValueError):
                pass
        video_path = work_dir / f"chunk-{plan.index:04d}.mp4"
        record: dict[str, Any] = {"index": plan.index, "start_seconds": plan.start_seconds,
                                  "end_seconds": plan.end_seconds, "status": "failed"}
        try:
            self._transcode(source, plan, video_path)
            payload = base64.b64encode(video_path.read_bytes()).decode("ascii")
            parts = [
                {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{payload}"},
                 "fps": self.settings.tutorial_study_fps},
                {"type": "text", "text": STUDY_PROMPT + "\n\n转写：\n" + self._transcript_lines(transcript, plan)},
            ]
            reply, usage = self.director.complete_json(parts, max_tokens=self.settings.tutorial_study_max_output_tokens,
                                                       model=self.model)
            parsed = StudyChunkReply.model_validate(reply)
            record.update({"status": "ok", "reply": parsed.model_dump(),
                           "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                                     "total_tokens": usage.total_tokens, "request_id": usage.workflow_run_id}})
        except ValidationError as error:
            record["error"] = f"invalid_reply:{str(error)[:800]}"
        except Exception as error:  # transport, transcode, JSON
            record["error"] = f"{type(error).__name__}:{str(error)[:800]}"
        finally:
            video_path.unlink(missing_ok=True)
        result_path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        return record

    # ---- whole lesson -------------------------------------------------------
    def study(self, source: Path, transcript: TranscriptResult, work_dir: Path, *,
              duration_seconds: float | None = None) -> LessonStudy:
        if not self.configured:
            raise RuntimeError("tutorial_study_not_configured")
        work_dir.mkdir(parents=True, exist_ok=True)
        duration = float(duration_seconds or transcript.duration_seconds or 0)
        if duration <= 0:
            duration = self.ffmpeg.probe_media(source).duration_seconds
        plans = self.plan(duration)
        workers = max(1, int(self.settings.tutorial_study_concurrency))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            records = list(pool.map(lambda plan: self._study_chunk(source, transcript, plan, work_dir), plans))

        segments: list[LessonStudySegment] = []
        rules: list[LessonStudyRule] = []
        uncertain: list[str] = []
        failed: list[dict] = []
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0}
        for plan, record in zip(plans, records, strict=True):
            if record.get("status") != "ok":
                failed.append({"index": plan.index, "start_seconds": plan.start_seconds,
                               "end_seconds": plan.end_seconds, "error": record.get("error", "unknown")})
                continue
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                usage[key] += int(record.get("usage", {}).get(key) or 0)
            usage["calls"] += 1
            reply = StudyChunkReply.model_validate(record["reply"])
            base_ms = int(plan.start_seconds * 1000)
            limit_ms = int(plan.end_seconds * 1000)

            def absolute(seconds: float) -> int:
                return max(base_ms, min(limit_ms, base_ms + int(round(seconds * 1000))))

            for segment in reply.segments:
                start_ms, end_ms = absolute(segment.start), absolute(segment.end)
                if end_ms <= start_ms:
                    end_ms = min(limit_ms, start_ms + 500)
                    if end_ms <= start_ms:
                        continue
                segments.append(LessonStudySegment(start_ms=start_ms, end_ms=end_ms, type=segment.type,
                                                   summary=segment.summary, teacher_actions=segment.teacher_actions,
                                                   chunk_index=plan.index))
                for rule in segment.rules:
                    rule_start, rule_end = absolute(rule.start), absolute(rule.end)
                    if rule_end <= rule_start:
                        rule_start, rule_end = start_ms, end_ms
                    rules.append(LessonStudyRule(category=rule.category, instruction=rule.instruction,
                                                 evidence_quote=rule.evidence_quote, start_ms=rule_start,
                                                 end_ms=rule_end, chunk_index=plan.index))
            uncertain.extend(reply.uncertain)
        segments.sort(key=lambda item: (item.start_ms, item.end_ms))
        rules.sort(key=lambda item: (item.start_ms, item.end_ms))
        digest = ""
        try:
            hasher = hashlib.sha256()
            with source.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(block)
            digest = hasher.hexdigest()
        except OSError:
            pass
        study = LessonStudy(source_name=source.name, source_sha256=digest, duration_seconds=duration, model=self.model,
                            fps=self.settings.tutorial_study_fps, chunk_seconds=int(self.settings.tutorial_study_chunk_seconds),
                            chunk_count=len(plans), completed_chunks=len(plans) - len(failed), failed_chunks=failed,
                            segments=segments, rules=rules, uncertain=uncertain, usage=usage)
        (work_dir / "lesson-study.json").write_text(study.model_dump_json(indent=1), encoding="utf-8")
        return study
