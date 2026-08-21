from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlmodel import Session, select
from sqlalchemy.orm import selectinload

from app.adapters.douyin import DouyinSearchClient
from app.adapters.public_trend_web import PublicTrendWebClient
from app.config import Settings
from app.db import Database
from app.models import (
    AutomationRun,
    AutomationRunDetail,
    AutomationSchedule,
    TaskStatus,
    TrendRecord,
    VideoTask,
)
from app.schemas.automation import DailyScheduleUpdate, TrendImportRecord
from app.services.pipeline_service import PipelineService
from app.services.material_library_service import MaterialLibraryService
from app.services.task_service import DuplicateTaskError, create_task_from_library_assets, get_task


def ensure_daily_schedule(session: Session, settings: Settings) -> AutomationSchedule:
    schedule = session.get(AutomationSchedule, "daily")
    if schedule is None:
        keywords = [item.strip() for item in settings.automation_keywords.split(",") if item.strip()]
        schedule = AutomationSchedule(
            enabled=settings.automation_enabled,
            hour=settings.automation_hour,
            minute=settings.automation_minute,
            timezone=settings.automation_timezone,
            keywords_json=json.dumps(keywords, ensure_ascii=False),
        )
        session.add(schedule)
        session.commit()
        session.refresh(schedule)
    return schedule


def schedule_to_dict(schedule: AutomationSchedule) -> dict[str, object]:
    return {
        "enabled": schedule.enabled,
        "hour": schedule.hour,
        "minute": schedule.minute,
        "timezone": schedule.timezone,
        "keywords": json.loads(schedule.keywords_json),
        "last_run_at": schedule.last_run_at,
    }


def update_daily_schedule(
    session: Session,
    schedule: AutomationSchedule,
    update: DailyScheduleUpdate,
) -> AutomationSchedule:
    schedule.enabled = update.enabled
    schedule.hour = update.hour
    schedule.minute = update.minute
    schedule.timezone = update.timezone
    schedule.keywords_json = json.dumps(update.keywords, ensure_ascii=False)
    schedule.updated_at = datetime.now(UTC)
    session.add(schedule)
    session.commit()
    session.refresh(schedule)
    return schedule


def import_trends(session: Session, records: list[TrendImportRecord]) -> int:
    inserted = 0
    for record in records:
        existing = session.exec(
            select(TrendRecord).where(
                TrendRecord.source == record.source,
                TrendRecord.keyword == record.keyword,
                TrendRecord.item_id == record.item_id,
            )
        ).first()
        if existing is not None:
            continue
        session.add(
            TrendRecord(
                source=record.source,
                source_type="public",
                keyword=record.keyword,
                item_id=record.item_id,
                title=record.title,
                url=record.url,
                digg_count=record.digg_count,
                author=record.author,
                cover_url=record.cover_url,
                high_quality_text=record.high_quality_text,
                evidence=record.evidence,
                published_at=record.published_at,
                captured_at=record.captured_at,
            )
        )
        inserted += 1
    session.commit()
    return inserted


def list_trends(session: Session, limit: int = 50) -> list[TrendRecord]:
    statement = select(TrendRecord).order_by(TrendRecord.captured_at.desc()).limit(limit)
    return list(session.exec(statement).all())


def list_automation_runs(session: Session, limit: int = 50) -> list[AutomationRun]:
    statement = (
        select(AutomationRun)
        .options(selectinload(AutomationRun.detail))
        .order_by(AutomationRun.started_at.desc())
        .limit(limit)
    )
    return list(session.exec(statement).all())


class DailyAutomation:
    def __init__(
        self,
        settings: Settings,
        pipeline: PipelineService,
        douyin: DouyinSearchClient,
        *,
        material_library: MaterialLibraryService | None = None,
        public_trends: PublicTrendWebClient | None = None,
    ):
        self.settings = settings
        self.pipeline = pipeline
        self.douyin = douyin
        self.material_library = material_library
        self.public_trends = public_trends

    @staticmethod
    def _best_trend(session: Session, keyword: str) -> TrendRecord | None:
        aliases = {"萌宠": "宠物", "毛孩子": "宠物", "猫咪": "猫", "狗狗": "狗"}
        variants = {keyword.strip()}
        for source, target in aliases.items():
            if source in keyword:
                variants.add(keyword.replace(source, target))
        rows = list(
            session.exec(
                select(TrendRecord).order_by(
                    TrendRecord.digg_count.desc(), TrendRecord.captured_at.desc()
                )
            ).all()
        )
        return next(
            (
                row
                for row in rows
                if any(value and (value in row.keyword or value in row.title) for value in variants)
            ),
            None,
        )

    def _create_daily_tasks(
        self,
        session: Session,
        schedule: AutomationSchedule,
        warnings: list[str],
    ) -> tuple[str, int, list[str]]:
        if not self.settings.automation_auto_create_tasks or self.material_library is None:
            return "disabled", 0, []

        created_task_ids: list[str] = []
        sourced_assets = 0
        material_status = "no_licensed_assets"
        local_date = datetime.now(UTC).astimezone(ZoneInfo(schedule.timezone)).date().isoformat()
        keywords = [item.strip() for item in json.loads(schedule.keywords_json) if item.strip()]
        task_limit = max(1, self.settings.automation_task_limit)
        for keyword in keywords:
            if len(created_task_ids) >= task_limit:
                break
            deduplication_key = f"daily-automation:{local_date}:{keyword}"
            if session.exec(
                select(VideoTask).where(VideoTask.deduplication_key == deduplication_key)
            ).first() is not None:
                continue
            acquisition = self.material_library.acquire(
                session,
                keyword,
                count=max(1, self.settings.automation_material_count),
            )
            material_status = acquisition.status
            if acquisition.warning:
                warnings.append(acquisition.warning)
            if not acquisition.assets:
                warnings.append(f"material_library_no_assets:{keyword}")
                continue

            trend = self._best_trend(session, keyword)
            trend_hint = trend.title if trend is not None else f"围绕“{keyword}”的高互动内容结构"
            requirements = (
                f"制作一条 20 到 30 秒的竖屏短视频，主题是“{keyword}”。"
                "前三秒必须给出明确冲突或收益点；中段用连续画面解释；结尾给出行动引导。"
                "旁白覆盖主体段落，字幕按语义分行并突出关键词。"
                f"热点参考：{trend_hint}。不得照搬原文或冒充原作者。"
            )
            try:
                task = create_task_from_library_assets(
                    session,
                    self.settings,
                    title=f"{keyword}治愈瞬间",
                    content_type="热点改编",
                    assets=acquisition.assets,
                    requirements_text=requirements,
                    quality_profile="production",
                    cloud_processing_allowed=True,
                    deduplication_key=deduplication_key,
                )
            except DuplicateTaskError:
                continue
            self.material_library.mark_used(session, acquisition.assets)
            created_task_ids.append(task.id)
            sourced_assets += len(acquisition.assets)
        return material_status, sourced_assets, created_task_ids

    def run(self, session: Session, schedule: AutomationSchedule, *, trigger: str) -> AutomationRun:
        run = AutomationRun(trigger=trigger)
        session.add(run)
        session.commit()
        session.refresh(run)

        warnings = []
        trend_status = self.douyin.status()["status"]
        trend_records = 0
        if trend_status == "configured":
            try:
                captured_at = datetime.now(UTC)
                imported = []
                for keyword in json.loads(schedule.keywords_json):
                    for video in self.douyin.search(keyword, count=10, publish_time=7, sort_type=1):
                        imported.append(
                            TrendImportRecord(
                                source="douyin_official_search",
                                keyword=keyword,
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
                        )
                trend_records = import_trends(session, imported) if imported else 0
                trend_status = "completed"
            except Exception as error:
                trend_status = "failed"
                warnings.append(f"trend_fetch_failed:{error}")
        elif self.public_trends is not None and self.public_trends.enabled:
            try:
                captured_at = datetime.now(UTC)
                imported = []
                for keyword in json.loads(schedule.keywords_json):
                    for evidence in self.public_trends.search(keyword, count=6):
                        imported.append(
                            TrendImportRecord(
                                source=evidence.source,
                                keyword=keyword,
                                item_id=evidence.item_id,
                                title=evidence.title,
                                url=evidence.url,
                                digg_count=0,
                                high_quality_text=evidence.summary,
                                captured_at=captured_at,
                                evidence="公开搜索结果元数据，仅用于选题证据；未下载平台视频",
                            )
                        )
                trend_records = import_trends(session, imported) if imported else 0
                trend_status = "public_web_completed" if imported else "reviewed_catalog_fallback"
                if not imported:
                    warnings.append("public_trend_web_no_results")
            except Exception as error:
                trend_status = "reviewed_catalog_fallback"
                warnings.append(f"public_trend_web_failed:{type(error).__name__}")
        else:
            trend_status = "reviewed_catalog_fallback" if list_trends(session, 1) else "not_configured"
            warnings.append("douyin_search_not_configured")

        material_status, sourced_assets, created_task_ids = self._create_daily_tasks(
            session, schedule, warnings
        )

        processed_tasks = 0
        failed_tasks = 0
        tasks = list(
            session.exec(select(VideoTask).where(VideoTask.status == TaskStatus.RECEIVED)).all()
        )
        for task in tasks:
            if not any(material.mime_type.lower().startswith("video/") for material in task.materials):
                continue
            try:
                current = get_task(session, task.id)
                if current is not None:
                    self.pipeline.process(session, current)
                    processed_tasks += 1
            except Exception as error:
                task.status = TaskStatus.FAILED
                session.add(task)
                session.commit()
                failed_tasks += 1
                warnings.append(f"task_failed:{task.id}:{error}")

        run.trend_status = trend_status
        run.trend_records = trend_records
        run.processed_tasks = processed_tasks
        run.failed_tasks = failed_tasks
        run.warning = ";".join(warnings)
        run.status = "completed_with_warnings" if warnings or failed_tasks else "completed"
        run.finished_at = datetime.now(UTC)
        schedule.last_run_at = run.finished_at
        run.detail = AutomationRunDetail(
            run_id=run.id,
            material_status=material_status,
            sourced_assets=sourced_assets,
            created_task_ids_json=json.dumps(created_task_ids, ensure_ascii=False),
            provider_summary_json=json.dumps(
                self.material_library.provider_counts(session) if self.material_library else {},
                ensure_ascii=False,
            ),
        )
        session.add(run)
        session.add(schedule)
        session.commit()
        session.refresh(run)
        run.__dict__["_material_status"] = material_status
        run.__dict__["_sourced_assets"] = sourced_assets
        run.__dict__["_created_task_ids"] = created_task_ids
        return run

    def is_due(self, schedule: AutomationSchedule, now: datetime) -> bool:
        if not schedule.enabled:
            return False
        local_now = now.astimezone(ZoneInfo(schedule.timezone))
        if (local_now.hour, local_now.minute) < (schedule.hour, schedule.minute):
            return False
        if schedule.last_run_at is None:
            return True
        last = schedule.last_run_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return last.astimezone(ZoneInfo(schedule.timezone)).date() < local_now.date()


class AutomationScheduler:
    def __init__(self, database: Database, settings: Settings, automation: DailyAutomation):
        self.database = database
        self.settings = settings
        self.automation = automation
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    def _run_due_sync(self) -> None:
        with Session(self.database.engine) as session:
            schedule = ensure_daily_schedule(session, self.settings)
            if self.automation.is_due(schedule, datetime.now(UTC)):
                self.automation.run(session, schedule, trigger="schedule")

    async def _loop(self) -> None:
        while not self._stop.is_set():
            await asyncio.to_thread(self._run_due_sync)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(10, self.settings.automation_poll_seconds))
            except TimeoutError:
                pass

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
