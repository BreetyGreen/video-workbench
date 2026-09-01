from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

from sqlmodel import Session, select

from app.adapters.dify import DifyClient
from app.adapters.jianying import edit_plan_from_timeline
from app.adapters.volcano_tts import TTSResult, VolcanoTTSClient
from app.config import Settings
from app.models import DeliveryState, EditingRecipe, EditingRule, Material, TaskStatus, TrendRecord, VideoTask
from app.schemas.analysis import EditRecipe, ViralAnalysis
from app.schemas.editing import MediaAnalysis
from app.services.draft_service import DraftService
from app.services.audio_routing_service import AudioRoutingService
from app.services.media_analysis_service import MediaAnalysisService
from app.services.quality_gate_service import QualityGateService
from app.services.reference_intelligence_service import ReferenceIntelligenceService
from app.services.render_service import RenderService
from app.services.task_service import get_task
from app.services.timeline_service import TimelinePlanner
from app.services.usage_service import UsageService
from app.services.course_recipe_service import CourseEditingPolicy, CourseRecipeService


class PipelineService:
    def __init__(
        self,
        settings: Settings,
        *,
        dify: DifyClient | None = None,
        analyzer: MediaAnalysisService | None = None,
        tts: VolcanoTTSClient | None = None,
        usage: UsageService | None = None,
    ):
        self.settings = settings
        self.dify = dify or DifyClient(settings)
        self.analyzer = analyzer or MediaAnalysisService(settings)
        self.tts = tts or VolcanoTTSClient(
            api_key=settings.volcano_tts_api_key or settings.volcano_asr_api_key,
            resource_id=settings.volcano_tts_resource_id,
            endpoint=settings.volcano_tts_endpoint,
            voice_type=settings.volcano_tts_voice_type,
            timeout_seconds=settings.volcano_tts_timeout_seconds,
            ffprobe_bin=settings.ffprobe_bin,
        )
        self.usage = usage or UsageService()
        self.audio_router = AudioRoutingService()
        self.planner = TimelinePlanner()
        self.renderer = RenderService(settings)
        self.drafts = DraftService(settings.artifact_dir, target="6+")
        self.reference_intelligence = ReferenceIntelligenceService()
        self.quality_gates = QualityGateService(settings)
        self.course_recipes = CourseRecipeService()

    def _course_policy(
        self,
        session: Session,
        task: VideoTask,
        analysis_dir: Path,
        evidence: list[str],
    ) -> CourseEditingPolicy | None:
        if not task.course_recipe_id:
            return None
        recipe = session.get(EditingRecipe, task.course_recipe_id)
        if recipe is None:
            raise ValueError("course_recipe_not_found")
        rules = list(
            session.exec(
                select(EditingRule)
                .where(EditingRule.recipe_id == recipe.id)
                .order_by(EditingRule.sort_order, EditingRule.id)
            ).all()
        )
        policy = self.course_recipes.compile(recipe, rules)
        (analysis_dir / "course-recipe.json").write_text(
            json.dumps(asdict(policy), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        evidence.append(
            f"课程配方：版本 {policy.version}，{len(policy.rules)} 条带教学视频证据的规则"
        )
        return policy

    def _record_usage(
        self,
        session: Session,
        warnings: list[str],
        *,
        task_id: str,
        provider: str,
        service: str,
        metric: str,
        quantity: float,
        unit: str,
        status: str = "succeeded",
        request_id: str = "",
        metadata: dict[str, object] | None = None,
    ) -> None:
        if quantity <= 0:
            return
        try:
            self.usage.record_event(
                session,
                task_id=task_id,
                provider=provider,
                service=service,
                metric=metric,
                quantity=quantity,
                unit=unit,
                status=status,
                request_id=request_id,
                metadata=metadata,
            )
        except Exception as error:
            warnings.append(f"云端用量记录失败（{service}/{metric}）：{type(error).__name__}")

    def _record_dify_usage(
        self,
        session: Session,
        task: VideoTask,
        warnings: list[str],
        *,
        workflow: str,
        applied: bool,
    ) -> None:
        usage = self.dify.last_usage
        if usage is None:
            return
        status = "succeeded" if applied else "succeeded_not_applied"
        metadata = {"workflow": workflow, "elapsed_time": usage.elapsed_time}
        for metric, quantity in (
            ("input_tokens", usage.input_tokens),
            ("output_tokens", usage.output_tokens),
            ("total_tokens", usage.total_tokens),
        ):
            self._record_usage(
                session,
                warnings,
                task_id=task.id,
                provider="dify",
                service="workflow",
                metric=metric,
                quantity=quantity,
                unit="tokens",
                status=status,
                request_id=usage.workflow_run_id,
                metadata=metadata,
            )

    @staticmethod
    def _tutorial_text(task: VideoTask) -> str:
        if task.tutorial_text:
            return task.tutorial_text
        parts = []
        for material in task.materials:
            if material.mime_type.split(";", 1)[0].strip().lower() != "text/plain":
                continue
            source = Path(material.stored_path)
            if source.is_file() and source.stat().st_size <= 1_000_000:
                parts.append(source.read_text(encoding="utf-8", errors="replace"))
        return "\n\n".join(parts).strip()

    @staticmethod
    def _trend_payload(session: Session, limit: int = 20) -> list[dict[str, object]]:
        trends = list(session.exec(select(TrendRecord).order_by(TrendRecord.digg_count.desc()).limit(limit)).all())
        return [
            {
                "source": item.source,
                "source_type": item.source_type,
                "keyword": item.keyword,
                "title": item.title,
                "url": item.url,
                "digg_count": item.digg_count,
                "author": item.author,
                "high_quality_text": item.high_quality_text,
                "evidence": item.evidence,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "captured_at": item.captured_at.isoformat(),
            }
            for item in trends
        ]

    @staticmethod
    def _baseline_copy(task: VideoTask) -> list[dict[str, object]]:
        brief = f"{task.title} {task.content_type} {task.requirements_text} {task.tutorial_text}".lower()
        if any(keyword in brief for keyword in ("帽", "hat", "头饰")):
            return [
                {
                    "title": "一顶显脸小的轻量遮阳帽，三个场景看上身效果",
                    "body": "通勤、旅行和周末出门怎么搭？这顶轻量遮阳帽用柔和帽檐修饰脸型，收纳轻松，也不压整体造型。视频展示三个真实上身场景，颜色与帽围请按自己的实际需求选择。",
                    "topics": ["遮阳帽", "帽子穿搭", "通勤穿搭", "旅行好物"],
                },
                {
                    "title": "帽子怎么选才不压造型？先看真实上身",
                    "body": "重点不是夸张滤镜，而是帽檐弧度、脸型修饰和不同场景的搭配效果。轻量好收纳，日常遮阳、通勤和出游都能直接用。",
                    "topics": ["显脸小帽子", "日常穿搭", "遮阳穿搭", "真实上身"],
                },
                {
                    "title": "轻便、好搭、能遮阳：这顶帽子适合哪些场景？",
                    "body": "用三个真实片段看帽子的正面、侧面和整体搭配。柔和帽檐自然修饰脸型，出门随手戴，放进行李也不占空间。实际颜色和尺寸以商品信息为准。",
                    "topics": ["轻量帽子", "旅行穿搭", "夏日遮阳", "帽子推荐"],
                },
            ]
        return [
            {
                "title": f"{task.title}｜版本{i}",
                "body": f"{task.title}。这是本地基线生成的候选文案，请结合真实内容人工修改。",
                "topics": [task.content_type, "日常记录"],
            }
            for i in range(1, 4)
        ]

    @staticmethod
    def _viral_copy_matches_task(task: VideoTask, viral: ViralAnalysis) -> bool:
        """Reject obviously off-topic workflow output before it reaches review."""
        brief = f"{task.title} {task.content_type} {task.requirements_text} {task.tutorial_text}".lower()
        subject_keywords = (
            "帽",
            "宠物",
            "猫",
            "狗",
            "除毛",
            "服装",
            "鞋",
            "包",
            "美妆",
            "护肤",
            "食品",
            "饮料",
            "家居",
            "数码",
            "手机",
            "汽车",
            "母婴",
            "玩具",
        )
        expected = {keyword for keyword in subject_keywords if keyword in brief}
        if not expected:
            return True
        copy_text = " ".join(
            f"{item.title} {item.body} {' '.join(item.topics)}" for item in viral.publish_copy
        ).lower()
        return any(keyword in copy_text for keyword in expected)

    @staticmethod
    def _write_analyses(path: Path, analyses: list[MediaAnalysis]) -> None:
        path.write_text(
            json.dumps([item.model_dump() for item in analyses], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _analysis_summary(analyses: list[MediaAnalysis]) -> dict[str, object]:
        return {
            "material_count": len(analyses),
            "transcribed_materials": sum(bool(item.transcript.segments) for item in analyses),
            "transcript_segments": sum(len(item.transcript.segments) for item in analyses),
            "scene_count": sum(len(item.scenes) for item in analyses),
            "silence_count": sum(len(item.silences) for item in analyses),
            "keyframe_count": sum(len(item.frames) for item in analyses),
            "ocr_text_count": sum(len(frame.ocr_texts) for item in analyses for frame in item.frames),
        }

    @staticmethod
    def _audio_material(task: VideoTask) -> Material | None:
        if not task.rights_confirmed:
            return None
        return next((item for item in task.materials if item.mime_type.lower().startswith("audio/")), None)

    @staticmethod
    def _narration_text(task: VideoTask, *, target_seconds: float = 22.0) -> str:
        title = task.title.strip() or "萌宠日常"
        category = task.content_type.strip() or "宠物"
        brief = f"{title} {category} {task.requirements_text} {task.tutorial_text}".lower()
        budget = min(105, max(9, round(max(1.0, target_seconds) * 4.7)))

        def fit(parts: list[str]) -> str:
            full = "".join(parts)
            if len(full) <= budget:
                return full
            chosen: list[str] = []
            used = 0
            for part in parts:
                if used + len(part) <= budget:
                    chosen.append(part)
                    used += len(part)
                    continue
                remaining = budget - used
                if remaining >= 6:
                    chosen.append(part[: remaining - 1].rstrip("，。！？；、 ") + "。")
                break
            return "".join(chosen) or parts[0][: budget - 1].rstrip("，。！？；、 ") + "。"

        if any(keyword in brief for keyword in ("商品", "产品", "带货", "卖点", "介绍")):
            if any(keyword in brief for keyword in ("帽", "hat", "头饰")):
                return fit(
                    [
                        "一顶帽子能不能显脸小，先看三个真实场景的上身效果。",
                        "柔和帽檐自然修饰脸型，日常遮阳也不压造型。",
                        "轻量好收纳，通勤、旅行和周末出门都容易搭配。",
                        "选适合自己的颜色和帽围，戴上就能轻松完成整套穿搭。",
                    ]
                )
            return fit(
                [
                    "沙发不再粘毛？先看这把宠物除毛梳怎么用。",
                    "顺着毛流轻梳，少量多次更温和。",
                    "画面只展示宠物状态，效果请以真实试用为准。",
                    "使用前先小范围尝试，按宠物反应调整力度，日常打理浮毛更轻松。",
                ]
            )
        return fit(
            [
                f"{title}，先看反差表情。",
                f"这组{category}实拍保留自然光和真实环境声。",
                "近景看细节，全景看整体。",
                "不虚构剧情，只分享画面里真实的小瞬间。",
                "喜欢就收藏这份真实日常。",
            ]
        )

    def _fit_voiceover(self, voiceover: TTSResult, *, target_seconds: float) -> tuple[TTSResult, float]:
        tolerance = self.settings.quality_duration_tolerance_seconds
        lower_bound = target_seconds * 0.9
        if lower_bound <= voiceover.duration_seconds <= target_seconds + tolerance:
            return voiceover, 1.0
        desired_seconds = max(
            0.3,
            target_seconds * (0.95 if voiceover.duration_seconds < lower_bound else 0.98),
        )
        speed_factor = voiceover.duration_seconds / desired_seconds
        factors: list[float] = []
        remaining = speed_factor
        while remaining > 2:
            factors.append(2.0)
            remaining /= 2
        while remaining < 0.5:
            factors.append(0.5)
            remaining /= 0.5
        factors.append(remaining)
        atempo = ",".join(f"atempo={factor:.6f}" for factor in factors)
        suffix = voiceover.path.suffix.lower() or ".mp3"
        fitted_path = voiceover.path.with_name(f"{voiceover.path.stem}-fitted{suffix}")
        command = [
            self.settings.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(voiceover.path),
            "-vn",
            "-af",
            atempo,
            "-y",
            str(fitted_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if completed.returncode != 0 or not fitted_path.is_file():
            raise RuntimeError(f"Voiceover time fitting failed: {completed.stderr[-240:]}")
        measured = self.quality_gates.ffmpeg.probe_media(fitted_path).duration_seconds
        return (
            TTSResult(
                path=fitted_path.resolve(),
                duration_seconds=measured,
                voice_type=voiceover.voice_type,
                character_count=voiceover.character_count,
            ),
            speed_factor,
        )

    def _cached_voiceover(
        self,
        analysis_dir: Path,
        *,
        narration_text: str,
        voice_type: str,
    ) -> TTSResult | None:
        route_path = analysis_dir / "audio-routing.json"
        if not route_path.is_file():
            return None
        try:
            route = json.loads(route_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if route.get("narration_text") != narration_text or route.get("voice_type") != voice_type:
            return None
        raw_path = route.get("voiceover_generated_path") or str(analysis_dir / "voiceover.mp3")
        candidate = Path(str(raw_path))
        if not candidate.is_file():
            fallback = analysis_dir / "voiceover.mp3"
            candidate = fallback if fallback.is_file() else candidate
        if not candidate.is_file():
            return None
        try:
            duration = self.quality_gates.ffmpeg.probe_media(candidate).duration_seconds
        except Exception:
            return None
        if duration <= 0:
            return None
        return TTSResult(
            path=candidate.resolve(),
            duration_seconds=duration,
            voice_type=voice_type,
            character_count=len(narration_text.strip()),
        )

    def _analyze_tutorial(
        self,
        session: Session,
        task: VideoTask,
        analyses: list[MediaAnalysis],
        analysis_dir: Path,
        evidence: list[str],
        warnings: list[str],
    ) -> EditRecipe | None:
        tutorial_text = self._tutorial_text(task)
        if not tutorial_text:
            warnings.append("未提供教程：当前使用本地视频理解与智能剪辑策略。")
            return None
        if not (self.settings.dify_base_url and self.settings.dify_tutorial_api_key):
            warnings.append("教程已保存，当前由本地智能剪辑引擎执行。")
            return None
        applied = False
        try:
            transcript = "\n".join(item.transcript.text for item in analyses if item.transcript.text)
            ocr = "\n".join(text for item in analyses for frame in item.frames for text in frame.ocr_texts)
            frame_descriptions = f"任务要求：{task.requirements_text}\n{ocr}".strip()
            recipe = self.dify.analyze_tutorial(
                {
                    "tutorial_text": tutorial_text,
                    "transcript": transcript,
                    "frame_descriptions": frame_descriptions,
                    "content_category": task.content_type,
                }
            )
            (analysis_dir / "edit-recipe.json").write_text(recipe.model_dump_json(indent=2), encoding="utf-8")
            evidence.append(
                f"Dify 教程配方：目标 {recipe.target_duration_seconds} 秒，{len(recipe.pacing)} 条节奏规则"
            )
            applied = True
            return recipe
        except Exception as error:
            warnings.append(f"Dify 教程分析失败，已回退本地配方：{type(error).__name__}")
            return None
        finally:
            self._record_dify_usage(session, task, warnings, workflow="tutorial", applied=applied)

    def _analyze_viral(
        self,
        session: Session,
        task: VideoTask,
        analysis_dir: Path,
        evidence: list[str],
        warnings: list[str],
    ) -> ViralAnalysis | None:
        trend_payload = self._trend_payload(session)
        if not trend_payload:
            warnings.append("趋势库暂无记录：未执行爆款模式分析。")
            return None
        if not (self.settings.dify_base_url and self.settings.dify_viral_api_key):
            warnings.append("Dify 爆款分析未配置：趋势证据已保存，当前使用本地候选文案。")
            return None
        applied = False
        try:
            viral = self.dify.analyze_viral(
                {
                    "content_category": task.content_type,
                    "trend_records": json.dumps(trend_payload, ensure_ascii=False),
                    "owner_metrics": "[]",
                }
            )
            (analysis_dir / "viral-analysis.json").write_text(viral.model_dump_json(indent=2), encoding="utf-8")
            if not self._viral_copy_matches_task(task, viral):
                warnings.append("Dify 候选文案与当前任务主题不相关，已回退到本地同主题文案。")
                return None
            evidence.append(f"Dify 爆款分析：使用 {len(trend_payload)} 条带来源公开趋势记录")
            evidence.extend(
                f"趋势证据：{item.metric}={item.value}（{item.source_type}）"
                for item in viral.evidence
            )
            applied = True
            return viral
        except Exception as error:
            warnings.append(f"Dify 爆款分析失败，已回退本地文案：{type(error).__name__}")
            return None
        finally:
            self._record_dify_usage(session, task, warnings, workflow="viral", applied=applied)

    def process(self, session: Session, task: VideoTask) -> VideoTask:
        videos = [item for item in task.materials if item.mime_type.lower().startswith("video/")]
        if not videos:
            raise ValueError("Local processing requires at least one video material")

        task.status = TaskStatus.ANALYZING
        session.add(task)
        session.commit()
        task_artifacts = self.settings.artifact_dir / task.id
        analysis_dir = task_artifacts / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        analyses = [
            self.analyzer.analyze(
                Path(material.stored_path),
                material_id=material.id,
                output_dir=analysis_dir / "keyframes",
                quality_profile=task.quality_profile,
                cloud_processing_allowed=task.cloud_processing_allowed,
            )
            for material in videos
        ]
        self._write_analyses(analysis_dir / "media-analysis.json", analyses)

        warnings = [warning for item in analyses for warning in item.warnings]
        for analysis in analyses:
            if analysis.transcript.provider == "volcano_bigasr":
                self._record_usage(
                    session,
                    warnings,
                    task_id=task.id,
                    provider="volcengine",
                    service="asr",
                    metric="audio_seconds",
                    quantity=analysis.transcript.duration_seconds or analysis.duration_seconds,
                    unit="seconds",
                    metadata={"material_id": analysis.material_id, "model": analysis.transcript.model},
                )
        if self.dify.status()["status"] != "configured":
            warnings.append("Dify 尚未配置完整：已使用本地视频理解和智能剪辑引擎。")
        evidence = [f"素材 {material.original_name} SHA-256：{material.sha256}" for material in videos]
        evidence.extend(
            f"视频理解：{item.width}×{item.height}，{item.duration_seconds:.2f} 秒，"
            f"{len(item.transcript.segments)} 段转写，{len(item.scenes)} 个场景，{len(item.frames)} 张关键帧"
            for item in analyses
        )
        model_routes = [
            {
                "material_id": item.material_id,
                "provider": item.transcript.provider or "disabled",
                "model": item.transcript.model or "none",
                "quality_profile": item.transcript.quality_profile or task.quality_profile,
                "fallback_reason": item.transcript.fallback_reason,
            }
            for item in analyses
        ]
        for route in model_routes:
            evidence.append(
                f"转写路由：{route['provider']} / {route['model']} / {route['quality_profile']}"
                + (f"，回退 {route['fallback_reason']}" if route["fallback_reason"] else "")
            )

        reference_brief = None
        if task.reference_path:
            try:
                reference_analysis = self.analyzer.analyze(
                    Path(task.reference_path),
                    material_id=f"reference-{task.id}",
                    output_dir=analysis_dir / "reference-keyframes",
                    quality_profile=task.quality_profile,
                    cloud_processing_allowed=task.cloud_processing_allowed,
                )
                (analysis_dir / "reference-media-analysis.json").write_text(
                    reference_analysis.model_dump_json(indent=2),
                    encoding="utf-8",
                )
                reference_brief = self.reference_intelligence.build(
                    reference_analysis,
                    source_name=task.reference_name or Path(task.reference_path).name,
                )
                (analysis_dir / "reference-video-brief.json").write_text(
                    reference_brief.model_dump_json(indent=2),
                    encoding="utf-8",
                )
                evidence.append(
                    f"参考片结构：{reference_brief.pacing.pace}，"
                    f"建议单镜头 {reference_brief.pacing.preferred_clip_seconds:.2f} 秒，"
                    f"钩子窗口 {reference_brief.pacing.hook_window_seconds:.2f} 秒"
                )
                warnings.extend(reference_brief.warnings)
                if reference_analysis.transcript.provider == "volcano_bigasr":
                    self._record_usage(
                        session,
                        warnings,
                        task_id=task.id,
                        provider="volcengine",
                        service="asr",
                        metric="audio_seconds",
                        quantity=reference_analysis.transcript.duration_seconds or reference_analysis.duration_seconds,
                        unit="seconds",
                        metadata={"material_id": reference_analysis.material_id, "model": reference_analysis.transcript.model, "reference": True},
                    )
            except Exception as error:
                warnings.append(f"参考片分析失败，已回退源素材智能剪辑：{type(error).__name__}")
        recipe = self._analyze_tutorial(session, task, analyses, analysis_dir, evidence, warnings)
        course_policy = self._course_policy(session, task, analysis_dir, evidence)
        viral = self._analyze_viral(session, task, analysis_dir, evidence, warnings)

        task.status = TaskStatus.PLANNING
        session.add(task)
        session.commit()
        planned_audio_mode = self.audio_router.planned_mode(analyses, content_type=task.content_type)
        target_seconds = min(
            22.0 if planned_audio_mode != "original" else 30.0,
            sum(item.duration_seconds for item in analyses),
        )
        audio = self._audio_material(task)
        preliminary_timeline = self.planner.plan(
            analyses,
            title=task.title,
            target_seconds=target_seconds,
            recipe=recipe,
            bgm_path=audio.stored_path if audio else None,
            reference_brief=reference_brief,
            audio_decision=None,
            course_policy=course_policy,
        )
        narration_text = self._narration_text(task, target_seconds=preliminary_timeline.actual_duration_seconds)
        voiceover = None
        generated_voiceover_seconds = 0.0
        voiceover_speed_factor = 1.0
        voiceover_cache_hit = False
        if planned_audio_mode != "original" and self.tts.configured:
            try:
                voiceover = self._cached_voiceover(
                    analysis_dir,
                    narration_text=narration_text,
                    voice_type=task.voice_type,
                )
                voiceover_cache_hit = voiceover is not None
                if voiceover is None:
                    try:
                        voiceover = self.tts.synthesize(
                            narration_text,
                            analysis_dir / "voiceover.mp3",
                            voice_type=task.voice_type,
                        )
                    except TypeError as error:
                        # Keep compatibility with narrow test/local adapters that
                        # predate per-task voice selection. The production adapter
                        # accepts the explicit voice_type keyword.
                        if "voice_type" not in str(error):
                            raise
                        voiceover = self.tts.synthesize(narration_text, analysis_dir / "voiceover.mp3")
                generated_voiceover_seconds = voiceover.duration_seconds
                voiceover, voiceover_speed_factor = self._fit_voiceover(
                    voiceover,
                    target_seconds=preliminary_timeline.actual_duration_seconds,
                )
                if not voiceover_cache_hit:
                    self._record_usage(
                        session,
                        warnings,
                        task_id=task.id,
                        provider="volcengine",
                        service="tts",
                        metric="characters",
                        quantity=voiceover.character_count,
                        unit="characters",
                        metadata={"voice_type": voiceover.voice_type},
                    )
                    self._record_usage(
                        session,
                        warnings,
                        task_id=task.id,
                        provider="volcengine",
                        service="tts",
                        metric="audio_seconds",
                        quantity=generated_voiceover_seconds,
                        unit="seconds",
                        metadata={
                            "voice_type": voiceover.voice_type,
                            "applied_seconds": voiceover.duration_seconds,
                            "speed_factor": round(voiceover_speed_factor, 4),
                        },
                    )
            except Exception as error:
                warnings.append(f"豆包旁白生成失败，已保留原始音轨：{type(error).__name__}")
        audio_decision = self.audio_router.decide(
            analyses,
            narration_text=narration_text,
            voiceover=voiceover,
            content_type=task.content_type,
        )
        if audio_decision.warning:
            warnings.append(audio_decision.warning)
        audio_route = {
            "mode": audio_decision.mode,
            "planned_mode": planned_audio_mode,
            "reason": audio_decision.reason,
            "original_gain_db": audio_decision.original_gain_db,
            "voiceover_used": bool(audio_decision.voiceover_path),
            "voiceover_path": audio_decision.voiceover_path,
            "voiceover_gain_db": audio_decision.voiceover_gain_db,
            "voice_type": audio_decision.voice_type,
            "voiceover_duration_seconds": audio_decision.voiceover_duration_seconds,
            "voiceover_generated_duration_seconds": generated_voiceover_seconds,
            "voiceover_generated_path": str(analysis_dir / "voiceover.mp3") if voiceover else "",
            "voiceover_speed_factor": round(voiceover_speed_factor, 4),
            "voiceover_cache_hit": voiceover_cache_hit,
            "narration_text": narration_text if audio_decision.voiceover_path else "",
            "warning": audio_decision.warning,
        }
        (analysis_dir / "audio-routing.json").write_text(
            json.dumps(audio_route, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        evidence.append(f"音频路由：{audio_decision.mode}；{audio_decision.reason}")
        final_target_seconds = target_seconds
        if audio_decision.voiceover_path and audio_decision.voiceover_duration_seconds > 0:
            final_target_seconds = min(target_seconds, audio_decision.voiceover_duration_seconds)
        baseline_timeline = None
        if course_policy is not None:
            baseline_timeline = self.planner.plan(
                analyses,
                title=task.title,
                target_seconds=final_target_seconds,
                recipe=recipe,
                bgm_path=audio.stored_path if audio else None,
                reference_brief=reference_brief,
                audio_decision=audio_decision,
            )
        timeline = self.planner.plan(
            analyses,
            title=task.title,
            target_seconds=final_target_seconds,
            recipe=recipe,
            bgm_path=audio.stored_path if audio else None,
            reference_brief=reference_brief,
            audio_decision=audio_decision,
            course_policy=course_policy,
        )
        if course_policy is not None and baseline_timeline is not None:
            comparison = self.course_recipes.compare(baseline_timeline, timeline, course_policy)
            (task_artifacts / "baseline-timeline.json").write_text(
                baseline_timeline.model_dump_json(indent=2),
                encoding="utf-8",
            )
            (task_artifacts / "course-rule-trace.json").write_text(
                json.dumps(
                    [item.model_dump(mode="json") for item in timeline.rule_trace],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (task_artifacts / "course-comparison.json").write_text(
                json.dumps(comparison, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            evidence.append(
                "课程规则已改变时间线：" + "、".join(comparison["meaningful_changes"])
            )
        (task_artifacts / "edit-timeline.json").write_text(timeline.model_dump_json(indent=2), encoding="utf-8")
        evidence.append(
            f"智能时间线：{len(timeline.clips)} 段剪辑，{timeline.source_count} 个素材源，"
            f"检测长静音 {timeline.removed_silence_seconds:.2f} 秒"
        )

        task.status = TaskStatus.EDITING
        session.add(task)
        session.commit()
        artifacts = self.renderer.render(timeline, task_artifacts)
        shutil.copy2(artifacts.report_path, task_artifacts / "preview.json")
        task_root = Path(videos[0].stored_path).parent
        package = self.drafts.generate(task.id, edit_plan_from_timeline(timeline, task_root))
        shutil.copy2(package.zip_path, task_artifacts / "draft.zip")

        quality_report = self.quality_gates.evaluate(
            preview_path=artifacts.preview_path,
            timeline=timeline,
            analyses=analyses,
            captions_path=artifacts.srt_path,
            draft_path=task_artifacts / "draft.zip",
            cover_path=artifacts.cover_path,
        )
        self.quality_gates.write(quality_report, task_artifacts / "quality-report.json")
        evidence.append(
            f"成片质量门禁：{quality_report.status}，"
            f"{len(quality_report.gates)} 项检查，{len(quality_report.blocking_failures)} 项阻断"
        )
        if quality_report.blocking_failures:
            warnings.append("成片存在阻断式质量问题，修复前无法批准。")
        elif quality_report.status == "warn":
            warnings.append("成片通过阻断式质量门禁，但仍有建议人工抽检的警告项。")

        warnings.append("尚未在本机剪映打开草稿，兼容性状态待人工确认。")
        manifest = {
            "aigc_declaration": "AI 辅助生成视频理解、剪辑时间线、字幕、封面、剪映草稿与候选文案，最终内容和发布由人工审核。",
            "evidence": evidence,
            "warnings": warnings,
            "publish_copy": [item.model_dump() for item in viral.publish_copy] if viral else self._baseline_copy(task),
            "analysis_summary": self._analysis_summary(analyses),
            "production_profile": {
                "quality_profile": task.quality_profile,
                "cloud_processing_allowed": task.cloud_processing_allowed,
                "reference_name": task.reference_name,
            },
            "model_routes": model_routes,
            "audio_route": audio_route,
            "reference_brief": reference_brief.model_dump() if reference_brief else None,
            "quality_report": quality_report.model_dump(),
            "timeline": [
                {
                    "material_id": clip.material_id,
                    "start_seconds": round(clip.timeline_start_seconds, 3),
                    "end_seconds": round(clip.timeline_end_seconds, 3),
                    "source_start_seconds": round(clip.source_start_seconds, 3),
                    "source_end_seconds": round(clip.source_end_seconds, 3),
                    "score": round(clip.score, 3),
                    "reason": clip.reason,
                }
                for clip in timeline.clips
            ],
        }
        (task_artifacts / "review.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        task.status = TaskStatus.REVIEWING
        task.delivery_state = DeliveryState.JIANYING_DRAFT
        session.add(task)
        session.commit()
        return get_task(session, task.id)  # type: ignore[return-value]
