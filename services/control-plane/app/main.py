from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
import hashlib
import json
import logging
from pathlib import Path
import platform as host_platform
import secrets
import shutil
from typing import Callable

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.adapters.dify import DifyClient
from app.adapters.douyin import DouyinSearchClient
from app.adapters.pexels import PexelsClient
from app.adapters.pixabay import PixabayClient
from app.adapters.public_trend_web import PublicTrendWebClient
from app.adapters.seedance import SeedanceClient
from app.adapters.douyin_publish import DouyinApiError, DouyinPublishClient
from app.adapters.volcano_tts import VolcanoTTSClient
from app.adapters.volcengine_usage import VolcengineUsageClient
from app.config import Settings
from app.db import Database
from app.models import CourseAssetRole, LicensedAsset, RightsStatus, TaskStatus
from app.platforms.runtime import resolve_runtime_paths
from app.schemas import (
    HealthRead,
    DouyinDeliveryRequest,
    ReviewDecision,
    ReviewEventRead,
    ReviewRequest,
    TaskArchiveRequest,
    TaskRead,
)
from app.schemas.automation import (
    AutomationRunRead,
    DailyScheduleRead,
    DailyScheduleUpdate,
    TrendImportRequest,
    TrendImportRecord,
    TrendDiscoveryRequest,
    TrendRead,
    XiaohongshuEvidenceImport,
)
from app.schemas.usage import CloudUsageSettingsUpdate
from app.schemas.voice import VoicePreviewRequest
from app.schemas.courses import CourseAssetRead, CourseRead
from app.schemas.materials import MaterialAcquisitionRequest
from app.schemas.provider_settings import ProviderSettingsUpdate
from app.schemas.setup import SetupPreferencesUpdate
from app.services.automation_service import (
    AutomationScheduler,
    DailyAutomation,
    ensure_daily_schedule,
    import_trends,
    list_automation_runs,
    list_trends,
    schedule_to_dict,
    update_daily_schedule,
)
from app.services.review_service import ReviewService, apply_review, list_review_events
from app.services.pipeline_service import PipelineService
from app.services.material_library_service import MaterialLibraryService
from app.services.cloud_usage_service import CloudUsageService, CredentialVerificationError
from app.services.authorized_video_intake import AuthorizedVideoIntake
from app.services.douyin_delivery_service import DouyinDeliveryService
from app.services.task_service import (
    DuplicateTaskError,
    archive_task,
    create_task,
    get_task,
    list_tasks,
    restore_task,
)
from app.services.usage_service import UsageService
from app.services.voice_catalog_service import VoiceCatalogService
from app.services.setup_service import SetupService
from app.services.provider_settings_service import ProviderSettingsService
from app.services.jianying_runtime_service import JianyingRuntimeService
from app.services.jianying_handoff_service import JianyingHandoffService
from app.services.course_intake_service import CourseIntakeError, CourseIntakeService
logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    dify_client: DifyClient | None = None,
    tts_client: VolcanoTTSClient | None = None,
    usage_client_factory: Callable[[str, str], VolcengineUsageClient] | None = None,
    douyin_search_client: DouyinSearchClient | None = None,
    douyin_publish_client: DouyinPublishClient | None = None,
) -> FastAPI:
    app_settings = settings or Settings()
    database = Database(app_settings.database_url)
    database.create_all()
    usage_key = app_settings.usage_secret_master_key.strip()
    if not usage_key:
        key_path = app_settings.data_dir / ".usage-secret-key"
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if not key_path.exists():
            key_path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        usage_key = key_path.read_text(encoding="utf-8").strip()
    provider_settings = ProviderSettingsService(usage_key)
    with Session(database.engine) as provider_session:
        provider_settings.import_legacy_settings(provider_session, app_settings)
        provider_settings.apply(provider_session, app_settings)
    review_service = ReviewService(app_settings.artifact_dir)
    analysis_client = dify_client or DifyClient(app_settings)
    speech_client = tts_client or VolcanoTTSClient(
        api_key=app_settings.volcano_tts_api_key or app_settings.volcano_asr_api_key,
        resource_id=app_settings.volcano_tts_resource_id,
        endpoint=app_settings.volcano_tts_endpoint,
        voice_type=app_settings.volcano_tts_voice_type,
        timeout_seconds=app_settings.volcano_tts_timeout_seconds,
        ffprobe_bin=app_settings.ffprobe_bin,
    )
    pipeline_service = PipelineService(app_settings, dify=analysis_client, tts=speech_client)
    douyin_client = douyin_search_client or DouyinSearchClient(app_settings)
    publish_client = douyin_publish_client or DouyinPublishClient()
    douyin_delivery = DouyinDeliveryService(publish_client, app_settings.artifact_dir)
    pexels_client = PexelsClient(
        api_key=app_settings.pexels_api_key,
        base_url=app_settings.pexels_api_base_url,
        timeout_seconds=app_settings.pexels_timeout_seconds,
        max_download_bytes=app_settings.pexels_max_download_bytes,
    )
    pixabay_client = PixabayClient(
        api_key=app_settings.pixabay_api_key,
        base_url=app_settings.pixabay_api_base_url,
        timeout_seconds=app_settings.pixabay_timeout_seconds,
        max_download_bytes=app_settings.pexels_max_download_bytes,
    )
    material_library = MaterialLibraryService(
        app_settings,
        pexels_client,
        pixabay=pixabay_client,
    )
    public_trend_client = PublicTrendWebClient(
        enabled=app_settings.public_trend_web_enabled,
        endpoint=app_settings.public_trend_web_endpoint,
        timeout_seconds=app_settings.public_trend_web_timeout_seconds,
    )
    seedance_client = SeedanceClient(
        api_key=app_settings.seedance_api_key,
        model=app_settings.seedance_model,
        base_url=app_settings.seedance_base_url,
    )
    authorized_video_intake = AuthorizedVideoIntake(app_settings)
    daily_automation = DailyAutomation(
        app_settings,
        pipeline_service,
        douyin_client,
        material_library=material_library,
        public_trends=public_trend_client,
    )
    automation_scheduler = AutomationScheduler(database, app_settings, daily_automation)
    app_dir = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(app_dir / "templates"))
    templates.env.globals["workbench_asset_version"] = hashlib.sha256(
        (app_dir / "static" / "workbench.js").read_bytes()
    ).hexdigest()[:12]
    cloud_usage = CloudUsageService(usage_key, usage_client_factory)
    voice_catalog = VoiceCatalogService(speech_client.voice_type)
    voice_usage = UsageService()
    setup_service = SetupService(app_settings.data_dir)
    jianying_runtime = JianyingRuntimeService(app_settings.data_dir)
    jianying_handoff = JianyingHandoffService(
        app_settings.data_dir,
        app_settings.artifact_dir,
        jianying_runtime,
    )
    course_intake = CourseIntakeService(
        app_settings.data_dir,
        app_settings.course_max_file_bytes,
    )

    def course_read(course, assets) -> CourseRead:
        return CourseRead(
            **course.model_dump(),
            assets=[CourseAssetRead.model_validate(asset) for asset in assets],
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        app_settings.data_dir.mkdir(parents=True, exist_ok=True)
        app_settings.material_dir.mkdir(parents=True, exist_ok=True)
        app_settings.artifact_dir.mkdir(parents=True, exist_ok=True)
        app_settings.library_dir.mkdir(parents=True, exist_ok=True)
        database.create_all()
        with Session(database.engine) as session:
            ensure_daily_schedule(session, app_settings)
        if app_settings.automation_enabled and app_settings.automation_scheduler_enabled:
            automation_scheduler.start()
            app.state.automation_scheduler_started = True
        try:
            yield
        finally:
            if app.state.automation_scheduler_started:
                await automation_scheduler.stop()

    app = FastAPI(title="Automated Video Workbench", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.database = database
    app.state.cloud_usage = cloud_usage
    app.state.provider_settings = provider_settings
    app.state.automation_scheduler_started = False
    app.mount("/static", StaticFiles(directory=str(app_dir / "static")), name="static")

    def session_dependency():
        yield from database.session()

    def local_runtime_snapshot() -> dict:
        system = host_platform.system()
        runtime_paths = resolve_runtime_paths(system=system, home=Path.home())
        jianying = jianying_runtime.snapshot()
        return {
            "platform": jianying.get("platform") or system,
            "architecture": jianying.get("architecture") or host_platform.machine(),
            "runtime": {
                "data_dir": str(app_settings.data_dir),
                "inbox_dir": str(runtime_paths.inbox_dir),
            },
            "tools": {
                "ffmpeg": shutil.which(app_settings.ffmpeg_bin) is not None,
                "ffprobe": shutil.which(app_settings.ffprobe_bin) is not None,
            },
            "jianying": jianying,
        }

    def material_status_snapshot(session: Session) -> dict:
        counts = material_library.provider_counts(session)
        return {
            "total": sum(counts.values()),
            "providers": counts,
            "pexels": (
                {"status": "configured", "provider": "pexels_official_api"}
                if pexels_client.configured
                else {
                    "status": "not_configured",
                    "provider": "pexels_official_api",
                    "reason": "missing_api_key",
                }
            ),
            "pixabay": pixabay_client.status(),
            "seedance": seedance_client.status(),
            "fallback": "rights_confirmed_local_catalog",
        }

    def integration_status_snapshot() -> dict[str, dict[str, str]]:
        missing_dingtalk = []
        if not app_settings.dingtalk_client_id:
            missing_dingtalk.append("client_id")
        if not app_settings.dingtalk_client_secret:
            missing_dingtalk.append("client_secret")
        dingtalk = (
            {"status": "configured"}
            if not missing_dingtalk
            else {
                "status": "not_configured",
                "reason": f"missing_{'_and_'.join(missing_dingtalk)}",
            }
        )
        return {
            "dify": analysis_client.status(),
            "dingtalk": dingtalk,
            "douyin": douyin_client.status(),
            "public_trends": public_trend_client.status(),
            "pixabay": pixabay_client.status(),
            "seedance": seedance_client.status(),
            "douyin_delivery": (
                {"status": "configured", "provider": "douyin_open_platform"}
                if app_settings.douyin_open_id and app_settings.douyin_access_token
                else {
                    "status": "oauth_required",
                    "provider": "douyin_open_platform",
                    "reason": "missing_open_id_or_access_token",
                }
            ),
            "materials": {
                "status": "configured",
                "provider": "pexels_official_api" if pexels_client.configured else "local_catalog",
                "fallback": "rights_confirmed_local_catalog",
            },
            "asr": (
                {"status": "configured", "provider": "volcano_bigasr"}
                if app_settings.volcano_asr_api_key
                or (app_settings.volcano_asr_app_key and app_settings.volcano_asr_access_key)
                else {
                    "status": "partially_configured",
                    "provider": "local_whisper",
                    "reason": "cloud_not_configured_local_quality_available",
                }
            ),
            "tts": (
                {
                    "status": "configured",
                    "provider": "doubao_tts_2_0",
                    "voice_type": speech_client.voice_type,
                }
                if speech_client.configured
                else {
                    "status": "not_configured",
                    "provider": "doubao_tts_2_0",
                    "reason": "missing_api_key",
                }
            ),
            "reference_intelligence": {
                "status": "configured",
                "provider": "local_structural",
            },
        }

    def setup_status_snapshot(session: Session) -> dict:
        return setup_service.status(
            runtime=local_runtime_snapshot(),
            integrations=integration_status_snapshot(),
            materials=material_status_snapshot(session),
        )

    @app.get("/health", response_model=HealthRead)
    def health() -> HealthRead:
        app_settings.material_dir.mkdir(parents=True, exist_ok=True)
        database.is_healthy()
        return HealthRead(status="ok", database="ok", artifact_storage="ok")

    @app.get("/", response_class=HTMLResponse)
    def workbench(request: Request):
        first_run = not setup_service.preferences()["local_mode_confirmed"]
        return templates.TemplateResponse(
            request,
            "workbench.html",
            {"show_onboarding": first_run},
        )

    @app.get("/setup", response_class=HTMLResponse)
    def setup_page(request: Request):
        return templates.TemplateResponse(request, "setup.html", {})

    @app.get("/docs/capabilities-and-configuration", response_class=HTMLResponse)
    def capability_guide(request: Request):
        return templates.TemplateResponse(
            request,
            "capabilities.html",
            {"capabilities": setup_service.capabilities.list()},
        )

    @app.get("/api/local-runtime")
    def local_runtime_status():
        return local_runtime_snapshot()

    @app.get("/api/setup/status")
    def setup_status(session: Session = Depends(session_dependency)):
        return setup_status_snapshot(session)

    @app.put("/api/setup/preferences")
    def update_setup_preferences(update: SetupPreferencesUpdate):
        return setup_service.update_preferences(local_mode_confirmed=update.local_mode_confirmed)

    @app.post("/api/setup/validate/{provider_id}")
    def validate_setup_provider(provider_id: str, session: Session = Depends(session_dependency)):
        cards = {card["id"]: card for card in setup_status_snapshot(session)["providers"]}
        if provider_id not in cards:
            raise HTTPException(status_code=404, detail={"code": "unknown_setup_provider"})
        return cards[provider_id]

    @app.get("/settings/cloud-usage", response_class=HTMLResponse)
    def cloud_usage_settings_page(request: Request):
        return templates.TemplateResponse(request, "cloud_usage_settings.html", {})

    @app.get("/settings/providers", response_class=HTMLResponse)
    def provider_settings_page(request: Request):
        return templates.TemplateResponse(request, "provider_settings.html", {})

    @app.get("/api/provider-settings")
    def read_provider_settings(session: Session = Depends(session_dependency)):
        return provider_settings.status(session)

    @app.put("/api/provider-settings/{provider_id}")
    def save_provider_settings(
        provider_id: str,
        update: ProviderSettingsUpdate,
        session: Session = Depends(session_dependency),
    ):
        try:
            return provider_settings.save(
                session,
                provider_id,
                values=update.values,
                clear_fields=update.clear_fields,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail={"code": "unknown_provider"}) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail={"code": str(error)}) from error

    @app.delete("/api/provider-settings/{provider_id}")
    def delete_provider_settings(provider_id: str, session: Session = Depends(session_dependency)):
        try:
            return provider_settings.delete(session, provider_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail={"code": "unknown_provider"}) from error

    @app.get("/voices", response_class=HTMLResponse)
    def voice_center_page(request: Request):
        return templates.TemplateResponse(request, "voices.html", {})

    @app.get("/materials", response_class=HTMLResponse)
    def material_center_page(request: Request):
        return templates.TemplateResponse(request, "materials.html", {})

    @app.get("/api/materials/status")
    def material_status(session: Session = Depends(session_dependency)):
        return material_status_snapshot(session)

    @app.get("/api/materials")
    def read_materials(
        query: str = "",
        limit: int = 60,
        session: Session = Depends(session_dependency),
    ):
        normalized_limit = min(max(limit, 1), 200)
        if query.strip():
            assets = material_library.search_local(session, query, limit=normalized_limit)
        else:
            from sqlmodel import select

            assets = list(
                session.exec(
                    select(LicensedAsset)
                    .order_by(LicensedAsset.created_at.desc())
                    .limit(normalized_limit)
                ).all()
            )
        payload = []
        for asset in assets:
            item = material_library.as_dict(asset)
            item["file_url"] = f"/api/materials/{asset.id}/file"
            payload.append(item)
        return {"assets": payload, "count": len(payload)}

    @app.post("/api/materials/reindex")
    def reindex_materials(session: Session = Depends(session_dependency)):
        result = material_library.sync_confirmed_assets(session)
        return {
            "imported": result.imported,
            "skipped_duplicates": result.skipped_duplicates,
            "providers": material_library.provider_counts(session),
        }

    @app.post("/api/materials/authorized-video")
    def upload_authorized_video(
        response: Response,
        file: UploadFile = File(...),
        source_type: str = Form(default="user_confirmed"),
        rights_basis: str = Form(..., min_length=1, max_length=1000),
        product_id: str = Form(default="", max_length=200),
        allowed_platforms: str = Form(..., min_length=1, max_length=500),
        search_text: str = Form(default="", max_length=1000),
        rights_expires_at: datetime | None = Form(default=None),
        session: Session = Depends(session_dependency),
    ):
        try:
            result = authorized_video_intake.ingest(
                session,
                upload=file,
                source_type=source_type,
                rights_basis=rights_basis,
                product_id=product_id,
                allowed_platforms=allowed_platforms.split(","),
                search_text=search_text,
                rights_expires_at=rights_expires_at,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail={"code": str(error)}) from error
        payload = material_library.as_dict(result.asset)
        payload["file_url"] = f"/api/materials/{result.asset.id}/file"
        response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
        return payload

    @app.post("/api/materials/acquire")
    def acquire_materials(
        request: MaterialAcquisitionRequest,
        session: Session = Depends(session_dependency),
    ):
        result = material_library.acquire(session, request.query, count=request.count)
        payload = []
        for asset in result.assets:
            item = material_library.as_dict(asset)
            item["file_url"] = f"/api/materials/{asset.id}/file"
            payload.append(item)
        return {
            "status": result.status,
            "warning": result.warning,
            "assets": payload,
            "count": len(payload),
        }

    @app.get("/api/materials/{asset_id}/file")
    def read_material_file(
        asset_id: str,
        session: Session = Depends(session_dependency),
    ):
        asset = session.get(LicensedAsset, asset_id)
        if asset is None:
            raise HTTPException(status_code=404, detail={"code": "material_not_found"})
        path = Path(asset.stored_path).resolve()
        root = app_settings.library_dir.resolve()
        if root not in path.parents or not path.is_file():
            raise HTTPException(status_code=404, detail={"code": "material_file_not_found"})
        return FileResponse(path, media_type=asset.mime_type, filename=asset.original_name)

    @app.get("/api/voices")
    def read_voice_catalog():
        return {
            "provider": "volcengine_official",
            "configured": speech_client.configured,
            "voices": voice_catalog.list(),
            "boundary": "仅使用平台官方音色；不提供未授权真人音色克隆。",
        }

    @app.post("/api/voices/{preset_id}/preview")
    def preview_voice(
        preset_id: str,
        preview: VoicePreviewRequest,
        session: Session = Depends(session_dependency),
    ):
        preset = voice_catalog.get(preset_id)
        if preset is None:
            raise HTTPException(status_code=404, detail={"code": "voice_not_found"})
        if not speech_client.configured:
            raise HTTPException(status_code=409, detail={"code": "tts_not_configured"})
        normalized = preview.text.strip()
        digest = hashlib.sha256(f"{preset.voice_type}\n{normalized}".encode("utf-8")).hexdigest()[:16]
        filename = f"{preset.preset_id}-{digest}.mp3"
        output = app_settings.data_dir / "voice-previews" / filename
        cached = output.is_file()
        if cached:
            character_count = len(normalized)
            duration_seconds = 0.0
            selected_voice = preset.voice_type
        else:
            try:
                result = speech_client.synthesize(normalized, output, voice_type=preset.voice_type)
            except Exception as error:
                logger.warning("voice_preview_failed preset=%s error=%s", preset_id, type(error).__name__)
                raise HTTPException(
                    status_code=502,
                    detail={"code": "voice_preview_failed", "reason": type(error).__name__},
                ) from error
            character_count = result.character_count
            duration_seconds = result.duration_seconds
            selected_voice = result.voice_type
            voice_usage.record_event(
                session,
                task_id=None,
                provider="volcengine",
                service="tts",
                metric="characters",
                quantity=character_count,
                unit="characters",
                metadata={"voice_type": selected_voice, "preset_id": preset_id, "preview": True},
            )
            if duration_seconds > 0:
                voice_usage.record_event(
                    session,
                    task_id=None,
                    provider="volcengine",
                    service="tts",
                    metric="audio_seconds",
                    quantity=duration_seconds,
                    unit="seconds",
                    metadata={"voice_type": selected_voice, "preset_id": preset_id, "preview": True},
                )
        return {
            "preset_id": preset_id,
            "voice_type": selected_voice,
            "audio_url": f"/api/voices/previews/{filename}",
            "character_count": character_count,
            "duration_seconds": duration_seconds,
            "cached": cached,
            "usage_notice": "首次试听会按实际字符记入本地用量；相同文本与音色命中缓存时不重复调用。",
        }

    @app.get("/api/voices/previews/{filename}")
    def read_voice_preview(filename: str):
        safe_name = Path(filename).name
        if safe_name != filename or not safe_name.endswith(".mp3"):
            raise HTTPException(status_code=404, detail={"code": "preview_not_found"})
        output = app_settings.data_dir / "voice-previews" / safe_name
        if not output.is_file():
            raise HTTPException(status_code=404, detail={"code": "preview_not_found"})
        return FileResponse(output, media_type="audio/mpeg", filename=safe_name)

    @app.get("/api/cloud-usage/settings")
    def read_cloud_usage_settings(session: Session = Depends(session_dependency)):
        return cloud_usage.settings(session)

    @app.put("/api/cloud-usage/settings")
    def write_cloud_usage_settings(update: CloudUsageSettingsUpdate, request: Request, session: Session = Depends(session_dependency)):
        origin = request.headers.get("origin", "")
        if origin and origin not in {"http://testserver", "http://127.0.0.1:8130", "http://localhost:8130"}:
            raise HTTPException(status_code=403, detail={"code": "cross_origin_write_rejected"})
        try:
            return cloud_usage.save(session, update)
        except CredentialVerificationError as error:
            logger.warning(
                "cloud_usage_credential_verification_failed stage=%s reason=%s http_status=%s request_id=%s",
                error.stage,
                error.reason,
                error.http_status,
                error.request_id,
            )
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "credential_verification_failed",
                    "stage": error.stage,
                    "reason": error.reason,
                    "http_status": error.http_status,
                    "request_id": error.request_id,
                },
            ) from error
        except Exception as error:
            raise HTTPException(status_code=400, detail={"code": "credential_verification_failed", "reason": type(error).__name__}) from error

    @app.get("/api/cloud-usage/summary")
    def read_cloud_usage_summary(session: Session = Depends(session_dependency)):
        return cloud_usage.summary(session)

    @app.post("/api/cloud-usage/refresh")
    def refresh_cloud_usage(session: Session = Depends(session_dependency)):
        return cloud_usage.summary(session, force=True)

    @app.get("/api/tasks/{task_id}/usage")
    def read_task_usage(task_id: str, session: Session = Depends(session_dependency)):
        if get_task(session, task_id) is None:
            raise HTTPException(status_code=404, detail={"code": "task_not_found"})
        return cloud_usage.usage.task_usage(session, task_id)

    @app.get("/api/integrations/status")
    def integration_status() -> dict[str, dict[str, str]]:
        return integration_status_snapshot()

    @app.get("/api/automations/daily", response_model=DailyScheduleRead)
    def read_daily_schedule(
        session: Session = Depends(session_dependency),
    ) -> DailyScheduleRead:
        schedule = ensure_daily_schedule(session, app_settings)
        return DailyScheduleRead.model_validate(schedule_to_dict(schedule))

    @app.put("/api/automations/daily", response_model=DailyScheduleRead)
    def put_daily_schedule(
        update: DailyScheduleUpdate,
        session: Session = Depends(session_dependency),
    ) -> DailyScheduleRead:
        schedule = update_daily_schedule(
            session,
            ensure_daily_schedule(session, app_settings),
            update,
        )
        return DailyScheduleRead.model_validate(schedule_to_dict(schedule))

    @app.post("/api/automations/daily/run", response_model=AutomationRunRead)
    def run_daily_automation(
        session: Session = Depends(session_dependency),
    ) -> AutomationRunRead:
        schedule = ensure_daily_schedule(session, app_settings)
        run = daily_automation.run(session, schedule, trigger="manual")
        return AutomationRunRead.model_validate(run)

    @app.get("/api/automations/runs", response_model=list[AutomationRunRead])
    def read_automation_runs(
        limit: int = 20,
        session: Session = Depends(session_dependency),
    ) -> list[AutomationRunRead]:
        normalized_limit = min(max(limit, 1), 200)
        return [
            AutomationRunRead.model_validate(run)
            for run in list_automation_runs(session, normalized_limit)
        ]

    @app.post("/api/trends/import")
    def post_trend_import(
        request: TrendImportRequest,
        session: Session = Depends(session_dependency),
    ) -> dict[str, int]:
        return {"inserted": import_trends(session, request.records)}

    @app.get("/trends", response_class=HTMLResponse)
    def trend_radar_page(request: Request):
        return templates.TemplateResponse(request, "trends.html", {})

    @app.post("/api/trends/discover")
    def discover_trends(
        request: TrendDiscoveryRequest,
        session: Session = Depends(session_dependency),
    ):
        state = douyin_client.status()
        if state.get("status") != "configured":
            raise HTTPException(
                status_code=409,
                detail={"code": "douyin_not_configured", "reason": state.get("reason", "unknown")},
            )
        try:
            videos = douyin_client.search(
                request.keyword,
                count=request.count,
                publish_time=request.publish_days,
                sort_type=1,
            )
        except Exception as error:
            logger.warning("douyin_trend_discovery_failed error=%s", type(error).__name__)
            raise HTTPException(
                status_code=502,
                detail={"code": "douyin_discovery_failed", "reason": str(error)[:240]},
            ) from error
        captured_at = datetime.now(UTC)
        records = [
            TrendImportRecord(
                source="douyin_official_search",
                keyword=request.keyword,
                item_id=video.item_id,
                title=video.title or video.item_id,
                url=video.url,
                digg_count=video.digg_count,
                author=video.author,
                cover_url=video.cover_url,
                high_quality_text=video.high_quality_text,
                captured_at=captured_at,
                published_at=video.published_at,
                evidence="抖音开放平台视频搜索公开返回字段",
            )
            for video in videos
        ]
        return {
            "source": "douyin_official_search",
            "keyword": request.keyword,
            "inserted": import_trends(session, records) if records else 0,
            "results": [record.model_dump(mode="json") for record in records],
            "evidence_boundary": "热度只是结构研究证据，不代表可复制内容或可直接发布。",
        }

    @app.post("/api/trends/xiaohongshu/import")
    def import_xiaohongshu_evidence(
        request: XiaohongshuEvidenceImport,
        session: Session = Depends(session_dependency),
    ):
        captured_at = datetime.now(UTC)
        item_id = hashlib.sha256(request.url.encode("utf-8")).hexdigest()[:24]
        record = TrendImportRecord(
            source="xiaohongshu_evidence",
            keyword=request.keyword,
            item_id=item_id,
            title=request.title,
            url=request.url,
            digg_count=request.engagement_count,
            author=request.author,
            captured_at=captured_at,
            evidence=f"人工导入的小红书公开页面证据：{request.evidence_note}",
        )
        return {
            "source": "xiaohongshu_evidence",
            "inserted": import_trends(session, [record]),
            "record": record.model_dump(mode="json"),
            "automation": "manual_evidence_only",
        }

    @app.get("/api/trends", response_model=list[TrendRead])
    def read_trends(
        limit: int = 50,
        session: Session = Depends(session_dependency),
    ) -> list[TrendRead]:
        normalized_limit = min(max(limit, 1), 500)
        return [
            TrendRead.model_validate(record)
            for record in list_trends(session, normalized_limit)
        ]

    @app.post("/api/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
    def post_task(
        title: str = Form(min_length=1, max_length=200),
        content_type: str = Form(min_length=1, max_length=100),
        rights_confirmed: bool = Form(),
        requirements_text: str = Form(default="", max_length=50_000),
        tutorial_text: str = Form(default="", max_length=50_000),
        quality_profile: str = Form(
            default="production",
            pattern="^(production|local_privacy|fast_preview)$",
        ),
        cloud_processing_allowed: bool = Form(default=False),
        voice_preset: str = Form(default="vivi-2", max_length=80),
        reference_file: UploadFile | None = File(default=None),
        source_type: str | None = Form(default=None, max_length=100),
        source_user: str | None = Form(default=None, max_length=200),
        source_conversation: str | None = Form(default=None, max_length=200),
        source_message_id: str | None = Form(default=None, max_length=200),
        deduplication_key: str | None = Form(default=None, max_length=300),
        files: list[UploadFile] = File(min_length=1),
        session: Session = Depends(session_dependency),
    ) -> TaskRead:
        selected_voice = voice_catalog.get(voice_preset)
        if selected_voice is None:
            raise HTTPException(status_code=422, detail={"code": "voice_not_found"})
        try:
            task = create_task(
                session,
                app_settings,
                title=title,
                content_type=content_type,
                rights_confirmed=rights_confirmed,
                files=files,
                requirements_text=requirements_text,
                tutorial_text=tutorial_text,
                quality_profile=quality_profile,
                cloud_processing_allowed=cloud_processing_allowed,
                voice_preset=selected_voice.preset_id,
                voice_type=selected_voice.voice_type,
                reference_file=reference_file,
                source_type=source_type,
                source_user=source_user,
                source_conversation=source_conversation,
                source_message_id=source_message_id,
                deduplication_key=deduplication_key,
            )
        except DuplicateTaskError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "duplicate_task", "deduplication_key": str(error)},
            ) from error
        return TaskRead.model_validate(task)

    @app.post("/api/courses/intake", response_model=CourseRead, status_code=status.HTTP_201_CREATED)
    def post_course_intake(
        response: Response,
        title: str = Form(min_length=1, max_length=200),
        source_type: str = Form(default="dingtalk", max_length=100),
        source_user: str = Form(default="", max_length=200),
        source_conversation: str = Form(default="", max_length=200),
        source_message_id: str = Form(min_length=1, max_length=300),
        asset_roles: str = Form(),
        rights_statuses: str = Form(),
        files: list[UploadFile] = File(min_length=1),
        session: Session = Depends(session_dependency),
    ) -> CourseRead:
        try:
            roles = [CourseAssetRole(value) for value in json.loads(asset_roles)]
            rights = [RightsStatus(value) for value in json.loads(rights_statuses)]
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_course_asset_metadata"},
            ) from error
        try:
            course, assets, created = course_intake.create_course(
                session,
                title=title,
                source_type=source_type,
                source_user=source_user,
                source_conversation=source_conversation,
                source_message_id=source_message_id,
                files=files,
                roles=roles,
                rights_statuses=rights,
            )
        except CourseIntakeError as error:
            status_code = 413 if error.code == "course_asset_too_large" else 422
            if error.code == "unsupported_course_asset_type":
                status_code = 415
            raise HTTPException(status_code=status_code, detail={"code": error.code}) from error
        if not created:
            response.status_code = status.HTTP_200_OK
        return course_read(course, assets)

    @app.get("/api/courses/{course_id}", response_model=CourseRead)
    def read_course(
        course_id: str,
        session: Session = Depends(session_dependency),
    ) -> CourseRead:
        result = course_intake.get_course(session, course_id)
        if result is None:
            raise HTTPException(status_code=404, detail={"code": "course_not_found"})
        return course_read(*result)

    @app.get("/api/tasks", response_model=list[TaskRead])
    def read_tasks(
        limit: int = 100,
        include_archived: bool = False,
        session: Session = Depends(session_dependency),
    ) -> list[TaskRead]:
        normalized_limit = min(max(limit, 1), 500)
        return [
            TaskRead.model_validate(task)
            for task in list_tasks(
                session,
                normalized_limit,
                include_archived=include_archived,
            )
        ]

    @app.post("/api/tasks/{task_id}/archive", response_model=TaskRead)
    def archive_existing_task(
        task_id: str,
        request: TaskArchiveRequest,
        session: Session = Depends(session_dependency),
    ) -> TaskRead:
        task = get_task(session, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail={"code": "task_not_found"})
        return TaskRead.model_validate(archive_task(session, task, request.reason))

    @app.post("/api/tasks/{task_id}/restore", response_model=TaskRead)
    def restore_existing_task(
        task_id: str,
        session: Session = Depends(session_dependency),
    ) -> TaskRead:
        task = get_task(session, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail={"code": "task_not_found"})
        return TaskRead.model_validate(restore_task(session, task))

    @app.post("/api/tasks/{task_id}/deliver/douyin", response_model=TaskRead)
    def deliver_task_to_douyin(
        task_id: str,
        request: DouyinDeliveryRequest,
        session: Session = Depends(session_dependency),
    ) -> TaskRead:
        if not app_settings.douyin_open_id.strip() or not app_settings.douyin_access_token.strip():
            raise HTTPException(status_code=409, detail={"code": "douyin_oauth_required"})
        task = get_task(session, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail={"code": "task_not_found"})
        try:
            updated, _ = douyin_delivery.deliver(
                session,
                task,
                title=request.title,
                visibility=request.visibility,
                open_id=app_settings.douyin_open_id,
                access_token=app_settings.douyin_access_token,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail={"code": str(error)}) from error
        except DouyinApiError as error:
            raise HTTPException(
                status_code=502,
                detail={"code": "douyin_provider_error", "provider_code": error.code, "message": error.description},
            ) from error
        return TaskRead.model_validate(updated)

    @app.get("/api/tasks/{task_id}", response_model=TaskRead)
    def read_task(
        task_id: str,
        session: Session = Depends(session_dependency),
    ) -> TaskRead:
        task = get_task(session, task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "task_not_found"},
            )
        return TaskRead.model_validate(task)

    @app.post("/api/tasks/{task_id}/process", response_model=TaskRead)
    def process_task(
        task_id: str,
        session: Session = Depends(session_dependency),
    ) -> TaskRead:
        task = get_task(session, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail={"code": "task_not_found"})
        try:
            processed = pipeline_service.process(session, task)
        except Exception as error:
            task.status = TaskStatus.FAILED
            session.add(task)
            session.commit()
            raise HTTPException(
                status_code=500,
                detail={"code": "processing_failed", "message": str(error)},
            ) from error
        try:
            jianying_handoff.import_task(task_id)
        except Exception:
            logger.exception("Automatic Jianying handoff failed for task %s", task_id)
        return TaskRead.model_validate(processed)

    @app.get("/api/tasks/{task_id}/handoff/jianying")
    def read_jianying_handoff(
        task_id: str,
        session: Session = Depends(session_dependency),
    ) -> dict[str, object]:
        if get_task(session, task_id) is None:
            raise HTTPException(status_code=404, detail={"code": "task_not_found"})
        return jianying_handoff.status(task_id)

    @app.post("/api/tasks/{task_id}/handoff/jianying")
    def import_jianying_handoff(
        task_id: str,
        session: Session = Depends(session_dependency),
    ) -> dict[str, object]:
        if get_task(session, task_id) is None:
            raise HTTPException(status_code=404, detail={"code": "task_not_found"})
        result = jianying_handoff.import_task(task_id)
        if result.get("status") == "failed":
            raise HTTPException(status_code=409, detail=result)
        return result

    @app.post("/api/tasks/{task_id}/review", response_model=TaskRead)
    def review_task(
        task_id: str,
        review: ReviewRequest,
        session: Session = Depends(session_dependency),
    ) -> TaskRead:
        task = get_task(session, task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "task_not_found"},
            )
        if review.decision == ReviewDecision.APPROVE and not task.rights_confirmed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "rights_not_confirmed"},
            )
        if review.decision == ReviewDecision.APPROVE:
            bundle = review_service.load_bundle(task_id)
            if bundle.missing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "missing_review_artifacts", "missing": bundle.missing},
                )
            if bundle.invalid_reason:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "invalid_review_manifest"},
                )
            if bundle.quality_invalid_reason:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "invalid_quality_report"},
                )
            if bundle.blocking_failures:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "quality_gates_failed",
                        "blocking_failures": bundle.blocking_failures,
                    },
                )
        updated = apply_review(
            session,
            task,
            decision=review.decision,
            comment=review.comment,
        )
        return TaskRead.model_validate(updated)

    @app.get("/api/tasks/{task_id}/review-events", response_model=list[ReviewEventRead])
    def review_events(
        task_id: str,
        session: Session = Depends(session_dependency),
    ) -> list[ReviewEventRead]:
        if get_task(session, task_id) is None:
            raise HTTPException(status_code=404, detail={"code": "task_not_found"})
        return [ReviewEventRead.model_validate(item) for item in list_review_events(session, task_id)]

    @app.get("/api/tasks/{task_id}/artifacts/{artifact_name}")
    def download_artifact(task_id: str, artifact_name: str) -> FileResponse:
        try:
            path = review_service.artifact_path(task_id, artifact_name)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail={"code": "artifact_not_found"}) from error
        return FileResponse(path, filename=path.name)

    @app.get("/api/tasks/{task_id}/manifest")
    def review_manifest(
        task_id: str,
        session: Session = Depends(session_dependency),
    ) -> dict[str, object]:
        task = get_task(session, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail={"code": "task_not_found"})
        bundle = review_service.load_bundle(task_id)
        return {
            "task_id": task.id,
            "title": task.title,
            "status": task.status,
            "rights_confirmed": task.rights_confirmed,
            "artifacts_complete": not bundle.missing,
            "missing_artifacts": bundle.missing,
            "manifest_valid": not bundle.invalid_reason,
            **bundle.manifest,
        }

    @app.get("/review/{task_id}", response_class=HTMLResponse)
    def review_page(
        request: Request,
        task_id: str,
        session: Session = Depends(session_dependency),
    ):
        task = get_task(session, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail={"code": "task_not_found"})
        bundle = review_service.load_bundle(task_id)
        quality_report = bundle.quality_report or {}
        gates = quality_report.get("gates", []) if isinstance(quality_report, dict) else []
        gates_by_name = {
            str(gate.get("name")): gate
            for gate in gates
            if isinstance(gate, dict) and gate.get("name")
        }
        narration_gate = gates_by_name.get("narration_coverage", {})
        narration_evidence = narration_gate.get("evidence", {}) if isinstance(narration_gate, dict) else {}
        narration_coverage = narration_evidence.get("coverage_percent") if isinstance(narration_evidence, dict) else None
        manifest = bundle.manifest
        audio_route = manifest.get("audio_route", {}) if isinstance(manifest, dict) else {}
        warnings = manifest.get("warnings", []) if isinstance(manifest, dict) else []
        review_issues = [
            {
                "kind": "quality",
                "status": gate.get("status", "warn"),
                "title": gate.get("name", "quality"),
                "message": gate.get("message", ""),
                "seek_seconds": gate.get("evidence", {}).get("start_seconds") if isinstance(gate.get("evidence"), dict) else None,
            }
            for gate in gates
            if isinstance(gate, dict) and gate.get("status") in {"fail", "warn"}
        ]
        review_issues.extend(
            {"kind": "warning", "status": "warn", "title": "生成警告", "message": str(item), "seek_seconds": None}
            for item in warnings
        )
        return templates.TemplateResponse(
            request,
            "review.html",
            {
                "task": task,
                "manifest": manifest,
                "missing": bundle.missing,
                "manifest_error": bool(bundle.invalid_reason),
                "has_preview": (bundle.task_dir / "preview.mp4").is_file(),
                "has_draft": (bundle.task_dir / "draft.zip").is_file(),
                "has_cover": (bundle.task_dir / "cover.jpg").is_file(),
                "has_captions": (bundle.task_dir / "captions.srt").is_file(),
                "has_timeline": (bundle.task_dir / "edit-timeline.json").is_file(),
                "has_render_report": (bundle.task_dir / "render-report.json").is_file(),
                "has_quality_report": (bundle.task_dir / "quality-report.json").is_file(),
                "quality_report": quality_report,
                "quality_invalid": bool(bundle.quality_invalid_reason),
                "quality_blocking": bool(bundle.blocking_failures),
                "task_usage": cloud_usage.usage.task_usage(session, task_id),
                "audio_route": audio_route,
                "narration_coverage": narration_coverage,
                "subtitle_coverage": narration_coverage if audio_route.get("voiceover_used") else None,
                "review_issues": review_issues,
                "jianying_handoff": jianying_handoff.status(task_id),
            },
        )

    return app


app = create_app()
