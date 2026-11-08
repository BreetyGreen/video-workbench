from __future__ import annotations

import json
import hashlib
import re
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

from sqlmodel import Session, select

from app.adapters.dashscope_speech import DashScopeCosyVoiceClient, DashScopeTTSClient
from app.adapters.dify import DifyClient, WorkflowUsage
from app.adapters.openai_compatible_director import OpenAICompatibleDirectorClient
from app.adapters.jianying import edit_plan_from_timeline
from app.services.caption_emphasis_service import product_terms_from_title
from app.adapters.volcano_tts import TTSResult, VolcanoTTSClient
from app.config import Settings
from app.models import DeliveryState, EditingRecipe, EditingRule, Material, TaskStatus, TrendRecord, VideoTask
from app.schemas.analysis import EditRecipe, ViralAnalysis
from app.schemas.editing import CaptionCue, EditingTimeline, MediaAnalysis
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
from app.services.director_service import (material_catalog, validate_director_sources, visual_frame_inputs,
                                         role_visual_frame_inputs, load_course_tutorial_analyses,
                                         repair_director_plan, narration_violations)
from app.services.narration_alignment_service import AlignmentResult, align_narration, inherit_caption_styles
from app.services.director_cache_service import director_cache_key, load_cached_recipe, save_cached_recipe


CLOUD_ASR_PROVIDERS = {"volcano_bigasr": "volcengine", "dashscope_paraformer": "dashscope"}


def build_tts_client(settings: Settings):
    """Pick the configured speech synthesizer (DashScope Qwen-TTS or Volcano)."""
    if settings.dashscope_speech_selected and settings.dashscope_tts_engine.strip().lower() == "cosyvoice":
        return DashScopeCosyVoiceClient(
            api_key=settings.dashscope_api_key,
            model=settings.dashscope_cosyvoice_model,
            voice_type=settings.dashscope_cosyvoice_voice,
            speech_rate=settings.dashscope_cosyvoice_speech_rate,
            ffprobe_bin=settings.ffprobe_bin,
        )
    if settings.dashscope_speech_selected:
        return DashScopeTTSClient(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
            model=settings.dashscope_tts_model,
            voice_type=settings.dashscope_tts_voice,
            instructions=settings.dashscope_tts_instructions,
            timeout_seconds=settings.dashscope_tts_timeout_seconds,
            ffmpeg_bin=settings.ffmpeg_bin,
            ffprobe_bin=settings.ffprobe_bin,
        )
    return VolcanoTTSClient(
        api_key=settings.volcano_tts_api_key or settings.volcano_asr_api_key,
        resource_id=settings.volcano_tts_resource_id,
        endpoint=settings.volcano_tts_endpoint,
        voice_type=settings.volcano_tts_voice_type,
        timeout_seconds=settings.volcano_tts_timeout_seconds,
        ffprobe_bin=settings.ffprobe_bin,
    )


class PipelineService:
    def __init__(
        self,
        settings: Settings,
        *,
        dify: DifyClient | None = None,
        director: OpenAICompatibleDirectorClient | None = None,
        analyzer: MediaAnalysisService | None = None,
        tts: VolcanoTTSClient | None = None,
        usage: UsageService | None = None,
    ):
        self.settings = settings
        self.dify = dify or DifyClient(settings)
        self.director = director or OpenAICompatibleDirectorClient(settings)
        self.analyzer = analyzer or MediaAnalysisService(settings)
        self.tts = tts or build_tts_client(settings)
        self.usage = usage or UsageService()
        self.audio_router = AudioRoutingService()
        self.planner = TimelinePlanner()
        self.renderer = RenderService(settings)
        self.drafts = DraftService(settings.artifact_dir, target="6+")
        self.reference_intelligence = ReferenceIntelligenceService()
        self.quality_gates = QualityGateService(settings)
        self.course_recipes = CourseRecipeService()

    def _align_voiceover(self, session, task, path: Path, text: str, duration: float,
                        analysis_dir: Path, warnings: list[str]) -> AlignmentResult:
        result = AlignmentResult([], 'unavailable', 'transcription_disabled')
        provider = model = ''
        if self.settings.transcription_enabled:
            try:
                transcript = self.analyzer.transcriber.transcribe(
                    path, quality_profile=task.quality_profile,
                    cloud_processing_allowed=task.cloud_processing_allowed)
                provider, model = transcript.provider, transcript.model
                if provider in CLOUD_ASR_PROVIDERS:
                    self._record_usage(session, warnings, task_id=task.id, provider=CLOUD_ASR_PROVIDERS[provider],
                        service='asr', metric='audio_seconds', quantity=transcript.duration_seconds or duration,
                        unit='seconds', metadata={'purpose': 'narration_alignment', 'model': model})
                (analysis_dir / 'narration-transcript.json').write_text(
                    transcript.model_dump_json(indent=2), encoding='utf-8')
                result = align_narration(text, transcript, duration)
                if any(cue.end_seconds > duration for cue in result.captions):
                    result = AlignmentResult([], 'unavailable', 'caption_exceeds_final_timeline')
            except Exception as error:
                result = AlignmentResult([], 'unavailable', f'transcription_failed:{type(error).__name__}')
        (analysis_dir / 'narration-alignment.json').write_text(json.dumps({
            'status': result.status, 'reason': result.reason, 'provider': provider, 'model': model,
            'captions': [cue.model_dump() for cue in result.captions],
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        return result

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
        client = self.director if (workflow == "tutorial" and getattr(self.director, "configured", False)) else self.dify
        usage = client.last_usage
        if usage is None:
            return
        provider_status = getattr(usage, 'status', 'succeeded')
        status = provider_status if provider_status != 'succeeded' else ("succeeded" if applied else "succeeded_not_applied")
        metadata = {"workflow": workflow, "elapsed_time": usage.elapsed_time}
        provider = "dify"
        service = "workflow"
        if client is self.director:
            provider = "openai_compatible"
            service = "chat"
            metadata["model"] = getattr(client, "model", "")
        for metric, quantity in (
            ("input_tokens", usage.input_tokens),
            ("output_tokens", usage.output_tokens),
            ("total_tokens", usage.total_tokens),
        ):
            self._record_usage(
                session,
                warnings,
                task_id=task.id,
                provider=provider,
                service=service,
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
    def _title_card(timeline: EditingTimeline, *, max_chars: int = 12, seconds: float = 1.4) -> CaptionCue | None:
        """Opening product-name card, only when the title is a short product name."""
        text = "".join(timeline.title.split())
        if not 1 <= len(text) <= max_chars or timeline.actual_duration_seconds < 1.0:
            return None
        end = min(seconds, timeline.actual_duration_seconds)
        return CaptionCue(material_id="title", text=text, start_seconds=0.0, end_seconds=end,
                          source_start_seconds=0.0, source_end_seconds=end, placement="middle", style="title")

    @staticmethod
    def _narration_text(task: VideoTask, *, target_seconds: float = 22.0, recipe: EditRecipe | None = None) -> str:
        if recipe is not None and recipe.director_plan is not None:
            return recipe.director_plan.narration
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
            subject = re.sub(r"^(?:做|制作|生成)(?:一个|一条)?\s*\d+\s*秒", "", title)
            subject = subject.split("｜")[0].removesuffix("商品介绍").strip()[:24] or "这件商品"
            return fit(
                [
                    f"{subject}，先看看这组素材。",
                    "商品特点和使用效果，请以实际规格与真实试用为准。",
                    "选购之前，先核对商品信息，再结合自己的使用需求。",
                    "这是一版素材预览，具体卖点需要确认后再补充。",
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

    @staticmethod
    def _voiceover_needs_timeline_fit(
        *,
        voiceover_seconds: float,
        timeline_seconds: float,
        tolerance_seconds: float,
    ) -> bool:
        return (
            voiceover_seconds - timeline_seconds > tolerance_seconds
            or voiceover_seconds < timeline_seconds * 0.9
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
        *,
        reference_analysis: MediaAnalysis | None = None,
    ) -> EditRecipe | None:
        visual_report = dict(version=1, transport_status='not_sent', frames=[],
                             model_visual_use='unknown', coverage='sampled_frames_not_full_video',
                             semantic_match='unknown')
        visual_report_path = analysis_dir / 'visual-input-evidence.json'
        visual_report_path.write_text(json.dumps(visual_report, ensure_ascii=False, indent=2), encoding='utf-8')
        tutorial_text = self._tutorial_text(task)
        if not tutorial_text:
            warnings.append("未提供教程：当前使用本地视频理解与智能剪辑策略。")
            return None
        if not task.cloud_processing_allowed:
            warnings.append("未同意云处理：未向 Dify 发送教程或素材证据。")
            return None
        use_director = bool(getattr(self.director, "configured", False))
        if not use_director and not (self.settings.dify_base_url and self.settings.dify_tutorial_api_key):
            warnings.append("教程已保存，当前由本地智能剪辑引擎执行。")
            return None
        applied = False
        cache_hit = False
        request_started = False
        try:
            tutorials = load_course_tutorial_analyses(session, getattr(task, 'course_recipe_id', None),
                                                     self.settings.data_dir)
            image_paths, frame_manifest = role_visual_frame_inputs(analyses, analysis_dir,
                reference=reference_analysis, tutorials=tutorials, tutorial_root=self.settings.data_dir)
            visual_report['frames'] = frame_manifest
            visual_report['transport_status'] = 'attempting' if image_paths else 'text_only'
            transcript = "\n".join(item.transcript.text for item in analyses if item.transcript.text)[:48000]
            frame_descriptions = json.dumps({
                "requirements": task.requirements_text[:2000],
                "total_materials": len(analyses),
                "catalog_is_bounded_sample": True,
                "material_catalog": material_catalog(analyses),
                "material_names": {
                    material.id: Path(material.original_name).name[:80]
                    for material in (getattr(task, "materials", None) or [])
                    if material.mime_type.split(";", 1)[0].strip().lower().startswith("video/")
                }
                if len(getattr(task, "materials", None) or []) <= 40
                else {},
                "material_name_policy": "文件名只是用户整理素材时的镜头提示，不是口味、品牌或功效事实；director_plan 的 material_id 必须填 material_catalog 里的 UUID，不能填文件名。",
                "visual_frames": frame_manifest,
                "reference_catalog": material_catalog([reference_analysis]) if reference_analysis else [],
                "tutorial_catalog": material_catalog(tutorials),
                "tutorial_policy": "tutorial_not_editable仅观察教学形式，讲解/软件操作/成片示例分类为本地候选，不是已验证的视觉分类；不得将示例口播当成当前商品事实。",
                "reference_policy": "reference_not_editable仅用于观察节奏/构图/字幕，不得用作成片素材或当前商品事实。",
                "limitations": "图像按image_index顺序附带，仅为素材抽样，未覆盖整片；商品事实和镜头语义尚未独立核验。" if image_paths else "只有OCR/转写，未发送实际图像。",
            }, ensure_ascii=False)
            inputs = {
                    "tutorial_text": tutorial_text,
                    "transcript": transcript,
                    "frame_descriptions": frame_descriptions,
                    "content_category": task.content_type,
                }
            if use_director:
                endpoint, scope, revision = self.director.endpoint, self.director.credential_scope, self.director.revision
                visual_report['director_provider'] = 'openai_compatible'
                visual_report['director_model'] = self.director.model
            else:
                endpoint = self.settings.dify_base_url
                scope = hashlib.sha256(self.settings.dify_tutorial_api_key.encode()).hexdigest()
                revision = self.settings.dify_tutorial_workflow_revision
                visual_report['director_provider'] = 'dify'
            key = director_cache_key(dict(inputs, endpoint=endpoint, credential_scope=scope), image_paths, revision)
            cache_dir = self.settings.data_dir / 'director-cache'
            recipe = load_cached_recipe(cache_dir, key) if key else None
            cache_hit = recipe is not None
            if not cache_hit:
                request_started = True
                client = self.director if use_director else self.dify
                recipe = client.analyze_tutorial(inputs, **({'image_paths': image_paths} if image_paths else {}))
                # Claim guard: one corrective retry when the narration uses a prohibited term.
                terms = [term.strip() for term in self.settings.prohibited_narration_terms.split(",") if term.strip()]
                violations = narration_violations(recipe.director_plan, terms) if recipe.director_plan else []
                if violations:
                    first_usage = client.last_usage
                    notice = "旁白违反禁止项，必须改写这些句子后重新输出完整 JSON（其余保持不变）：" + "；".join(
                        f"第{index}段“{narration}”含禁止词“{term}”" for index, term, narration in violations[:8])
                    retry_inputs = dict(inputs, tutorial_text=f"{tutorial_text}\n\n{notice}")
                    retry = client.analyze_tutorial(retry_inputs, **({'image_paths': image_paths} if image_paths else {}))
                    retry_violations = narration_violations(retry.director_plan, terms) if retry.director_plan else []
                    visual_report['claim_guard'] = {
                        "first_pass": [f"beat {i}: {t}" for i, t, _ in violations],
                        "retry": [f"beat {i}: {t}" for i, t, _ in retry_violations],
                    }
                    if first_usage is not None and client.last_usage is not None:
                        # Bill both calls: the retry's usage is added onto the rejected first pass.
                        merged = WorkflowUsage(
                            workflow_run_id=client.last_usage.workflow_run_id,
                            input_tokens=first_usage.input_tokens + client.last_usage.input_tokens,
                            output_tokens=first_usage.output_tokens + client.last_usage.output_tokens,
                            total_tokens=first_usage.total_tokens + client.last_usage.total_tokens,
                            elapsed_time=first_usage.elapsed_time + client.last_usage.elapsed_time,
                            status=client.last_usage.status,
                        )
                        client.last_usage = merged
                    if retry_violations:
                        raise ValueError("director_narration_prohibited_terms:" + ",".join(t for _, t, _ in retry_violations))
                    recipe = retry
                    warnings.append(f"旁白首稿含禁止词（{'、'.join(sorted({t for _, t, _ in violations}))}），已按禁止项重写一次。")
            visual_report['cache_hit'] = cache_hit
            visual_report['workflow_revision'] = revision or 'unknown'
            visual_report['transport_status'] = ('cached_no_request' if cache_hit else
                                                 'workflow_returned' if image_paths else 'text_only')
            if cache_hit:
                evidence.append('分镜复用：相同输入、图像内容与已知工作流版本；本轮没有重复云请求。')
            elif image_paths:
                evidence.append(f"素材视觉输入：{len(image_paths)} 张抽样图像已随工作流请求发送；模型实际使用图像及语义正确性尚未独立验证。")
            else:
                warnings.append("没有可发送的有效任务关键帧，本次 Dify 只收到文字证据。")
            if recipe.director_plan is not None:
                name_aliases: dict[str, str] = {}
                for material in (getattr(task, "materials", None) or []):
                    if not material.mime_type.split(";", 1)[0].strip().lower().startswith("video/"):
                        continue
                    name = Path(material.original_name).name
                    stem = Path(name).stem
                    candidates = {name, stem, stem.split("-", 1)[0], stem.rsplit("-", 1)[-1]}
                    for alias in candidates:
                        alias = alias.strip()
                        if alias and name_aliases.get(alias, material.id) == material.id:
                            name_aliases[alias] = material.id
                        elif alias in name_aliases:
                            name_aliases[alias] = ""  # ambiguous label, never map it
                repaired_plan, repairs = repair_director_plan(recipe.director_plan, analyses, aliases=name_aliases)
                if repairs:
                    recipe = recipe.model_copy(update={"director_plan": repaired_plan,
                                                       "notes": [*recipe.notes, *[f"repair:{note}" for note in repairs]]})
                    visual_report['plan_repairs'] = repairs
                    warnings.append(f"分镜计划做了 {len(repairs)} 处机械修正（素材名映射/越界裁剪/重叠丢弃），详见 visual-input-evidence.json。")
                validate_director_sources(recipe.director_plan, analyses)
            if key and not cache_hit:
                try:
                    save_cached_recipe(cache_dir, key, recipe)
                except (OSError, ValueError):
                    warnings.append('分镜缓存保存失败，本轮有效配方仍继续使用。')
            (analysis_dir / "edit-recipe.json").write_text(recipe.model_dump_json(indent=2), encoding="utf-8")
            evidence.append(
                f"{'导演模型 ' + self.director.model if use_director else 'Dify 教程'}配方："
                f"目标 {recipe.target_duration_seconds} 秒，{len(recipe.pacing)} 条节奏规则"
            )
            applied = True
            return recipe
        except Exception as error:
            if visual_report['transport_status'] == 'attempting':
                visual_report['transport_status'] = 'failed_or_partial'
            warnings.append(f"{'导演模型' if use_director else 'Dify 教程'}分析失败，已回退本地配方：{type(error).__name__}")
            failure = {"error_type": type(error).__name__, "message": str(error)[:2000],
                       "raw_response_excerpt": str(getattr(error, "raw_response", ""))[:20000]}
            visual_report['failure'] = {"error_type": failure["error_type"], "message": failure["message"][:300]}
            try:
                (analysis_dir / "director-error.json").write_text(
                    json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError:
                pass
            return None
        finally:
            visual_report_path.write_text(json.dumps(visual_report, ensure_ascii=False, indent=2), encoding='utf-8')
            if request_started:
                self._record_dify_usage(session, task, warnings, workflow="tutorial", applied=applied)

    def _analyze_viral(
        self,
        session: Session,
        task: VideoTask,
        analysis_dir: Path,
        evidence: list[str],
        warnings: list[str],
    ) -> ViralAnalysis | None:
        if not task.cloud_processing_allowed:
            warnings.append("未同意云处理：未向 Dify 发送趋势分析请求。")
            return None
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
            if analysis.transcript.provider in CLOUD_ASR_PROVIDERS:
                self._record_usage(
                    session,
                    warnings,
                    task_id=task.id,
                    provider=CLOUD_ASR_PROVIDERS[analysis.transcript.provider],
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
        reference_analysis = None
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
                if reference_analysis.transcript.provider in CLOUD_ASR_PROVIDERS:
                    self._record_usage(
                        session,
                        warnings,
                        task_id=task.id,
                        provider=CLOUD_ASR_PROVIDERS[reference_analysis.transcript.provider],
                        service="asr",
                        metric="audio_seconds",
                        quantity=reference_analysis.transcript.duration_seconds or reference_analysis.duration_seconds,
                        unit="seconds",
                        metadata={"material_id": reference_analysis.material_id, "model": reference_analysis.transcript.model, "reference": True},
                    )
            except Exception as error:
                warnings.append(f"参考片分析失败，已回退源素材智能剪辑：{type(error).__name__}")
        recipe = self._analyze_tutorial(session, task, analyses, analysis_dir, evidence, warnings,
                                       reference_analysis=reference_analysis)
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
        narration_text = self._narration_text(task, target_seconds=preliminary_timeline.actual_duration_seconds, recipe=recipe)
        director = recipe.director_plan if recipe else None
        director_report = {
            "version": 1,
            "mode": "director_plan" if director else "legacy_local_preview",
            "plan": director.model_dump() if director else None,
            "source_ranges_verified": director is not None,
            "semantic_match": "unknown", "product_claims": "unknown",
            "style_match": "unknown", "native_playback": "unknown",
        }
        warnings.append("内容/参考风格尚未独立验收；技术质检通过不代表参考效果达标。")
        if director is None:
            warnings.append("未获得统一分镜计划：当前为本地模板预览，不是参考驱动成片。")
        (task_artifacts / "director-plan.json").write_text(
            json.dumps(director_report, ensure_ascii=False, indent=2), encoding="utf-8")
        voiceover = None
        generated_voiceover_seconds = 0.0
        voiceover_speed_factor = 1.0
        voiceover_cache_hit = False
        director_stretch_seconds: float | None = None
        if planned_audio_mode != "original" and task.cloud_processing_allowed and self.tts.configured:
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
                if (director is not None and generated_voiceover_seconds
                        > preliminary_timeline.actual_duration_seconds + self.settings.quality_duration_tolerance_seconds):
                    stretched = self.planner.plan(
                        analyses, title=task.title,
                        target_seconds=max(target_seconds, min(self.planner.max_automatic_seconds, generated_voiceover_seconds)),
                        recipe=recipe, bgm_path=audio.stored_path if audio else None, reference_brief=reference_brief,
                        audio_decision=None, course_policy=course_policy, stretch_to_seconds=generated_voiceover_seconds,
                    )
                    if stretched.actual_duration_seconds > preliminary_timeline.actual_duration_seconds + 0.05:
                        preliminary_timeline = stretched
                        director_stretch_seconds = generated_voiceover_seconds
                        target_seconds = max(target_seconds, stretched.actual_duration_seconds)
                        evidence.extend(stretched.warnings)
                voiceover, voiceover_speed_factor = self._fit_voiceover(
                    voiceover,
                    target_seconds=preliminary_timeline.actual_duration_seconds,
                )
                if not voiceover_cache_hit:
                    tts_provider = getattr(self.tts, "provider_name", "volcengine")
                    self._record_usage(
                        session,
                        warnings,
                        task_id=task.id,
                        provider=tts_provider,
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
                        provider=tts_provider,
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
                warnings.append(f"旁白生成失败（{getattr(self.tts, 'provider_name', 'volcengine')}），已保留原始音轨：{type(error).__name__}")
        audio_decision = self.audio_router.decide(
            analyses,
            narration_text=narration_text,
            voiceover=voiceover,
            content_type=task.content_type,
            product_terms=product_terms_from_title(task.title),
        )
        if audio_decision.warning:
            warnings.append(audio_decision.warning)
        if not task.cloud_processing_allowed and planned_audio_mode != "original":
            warnings.append("未同意云处理：未调用云端配音，保留原始音轨。")
        director_report["narration_applied"] = bool(audio_decision.voiceover_path)
        director_report["caption_alignment"] = "character_weighted_not_word_verified"
        (task_artifacts / "director-plan.json").write_text(
            json.dumps(director_report, ensure_ascii=False, indent=2), encoding="utf-8")
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
                stretch_to_seconds=director_stretch_seconds,
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
            stretch_to_seconds=director_stretch_seconds,
        )
        if (
            voiceover is not None
            and audio_decision.voiceover_path
            and self._voiceover_needs_timeline_fit(
                voiceover_seconds=audio_decision.voiceover_duration_seconds,
                timeline_seconds=timeline.actual_duration_seconds,
                tolerance_seconds=self.settings.quality_duration_tolerance_seconds,
            )
        ):
            voiceover, final_fit_factor = self._fit_voiceover(
                voiceover,
                target_seconds=timeline.actual_duration_seconds,
            )
            voiceover_speed_factor *= final_fit_factor
            audio_decision = self.audio_router.decide(
                analyses,
                narration_text=narration_text,
                voiceover=voiceover,
                content_type=task.content_type,
                product_terms=product_terms_from_title(task.title),
            )
            timeline.audio = timeline.audio.model_copy(
                update={
                    "mode": audio_decision.mode,
                    "original_gain_db": audio_decision.original_gain_db,
                    "voiceover_path": audio_decision.voiceover_path,
                    "voiceover_gain_db": audio_decision.voiceover_gain_db,
                    "voice_type": audio_decision.voice_type,
                    "voiceover_duration_seconds": audio_decision.voiceover_duration_seconds,
                    "decision_reason": audio_decision.reason,
                }
            )
            timeline.captions = list(audio_decision.captions)
            audio_route.update(
                {
                    "mode": audio_decision.mode,
                    "reason": audio_decision.reason,
                    "original_gain_db": audio_decision.original_gain_db,
                    "voiceover_path": audio_decision.voiceover_path,
                    "voiceover_gain_db": audio_decision.voiceover_gain_db,
                    "voice_type": audio_decision.voice_type,
                    "voiceover_duration_seconds": audio_decision.voiceover_duration_seconds,
                    "voiceover_speed_factor": round(voiceover_speed_factor, 4),
                    "warning": audio_decision.warning,
                }
            )
            (analysis_dir / "audio-routing.json").write_text(
                json.dumps(audio_route, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if timeline.audio.voiceover_path:
            alignment = self._align_voiceover(session, task, Path(timeline.audio.voiceover_path),
                narration_text, timeline.actual_duration_seconds, analysis_dir, warnings)
            if alignment.status == 'word_aligned':
                timeline.captions = inherit_caption_styles(alignment.captions, timeline.captions)
                evidence.append('旁白字幕：完整文案与最终音频逐词时间匹配。')
            else:
                warnings.append(f'旁白字幕使用估算时间，未通过逐词核验：{alignment.reason}')
            director_report['caption_alignment'] = (alignment.status if alignment.status == 'word_aligned'
                                                    else 'character_weighted_not_word_verified')
            audio_route['caption_alignment'] = director_report['caption_alignment']
            (task_artifacts / 'director-plan.json').write_text(
                json.dumps(director_report, ensure_ascii=False, indent=2), encoding='utf-8')
            (analysis_dir / 'audio-routing.json').write_text(
                json.dumps(audio_route, ensure_ascii=False, indent=2), encoding='utf-8')
        title_card = self._title_card(timeline)
        if title_card is not None:
            timeline.captions = [title_card, *timeline.captions]
            evidence.append(f"片头标题：{title_card.text}，{title_card.end_seconds:.1f} 秒居中大字，同时进入剪映文本轨。")
        else:
            evidence.append("未加片头标题：任务标题不是 12 字以内的商品名。")
        director_report["title_card"] = title_card.text if title_card else None
        (task_artifacts / "director-plan.json").write_text(
            json.dumps(director_report, ensure_ascii=False, indent=2), encoding="utf-8")
        if course_policy is not None and baseline_timeline is not None:
            comparison = (self.course_recipes.compare(baseline_timeline, timeline, course_policy)
                          if director is None else {
                              "status": "unknown", "meaningful_changes": [],
                              "reason": "director_plan_course_rule_application_not_independently_verified",
                          })
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
            evidence.append("课程规则已改变时间线：" + "、".join(comparison["meaningful_changes"])
                            if comparison["status"] == "pass" else "分镜计划已应用；课程规则效果尚未独立验证。")
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
        package = self.drafts.generate(
            task.id,
            edit_plan_from_timeline(timeline, task_root, highlight_color=self.settings.caption_highlight_color,
                                    pop_in=self.settings.caption_pop_in),
        )
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
            "creative_validation": director_report,
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
