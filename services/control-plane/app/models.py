from datetime import UTC, datetime
from enum import StrEnum
from typing import Optional
from uuid import uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel


class TaskStatus(StrEnum):
    RECEIVED = "received"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    EDITING = "editing"
    REVIEWING = "reviewing"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    DELIVERED = "delivered"
    FAILED = "failed"


class DeliveryState(StrEnum):
    JIANYING_DRAFT = "jianying_draft"
    DOUYIN_SELF_VISIBLE = "douyin_self_visible"
    DOUYIN_PUBLISHED = "douyin_published"


class CourseAssetRole(StrEnum):
    TUTORIAL = "tutorial"
    REFERENCE = "reference"
    MATERIAL = "material"


class RightsStatus(StrEnum):
    UNKNOWN = "unknown"
    PERSONAL_LEARNING = "personal_learning"
    COMMERCIAL_AUTHORIZED = "commercial_authorized"


class Course(SQLModel, table=True):
    __tablename__ = "courses"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    title: str
    source_type: str = Field(default="dingtalk", index=True)
    source_user: str = ""
    source_conversation: str = ""
    source_message_id: str = Field(index=True, unique=True)
    status: str = Field(default="received", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CourseAsset(SQLModel, table=True):
    __tablename__ = "course_assets"
    __table_args__ = (
        UniqueConstraint("course_id", "sha256", "role", name="uq_course_asset_hash_role"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    course_id: str = Field(foreign_key="courses.id", index=True)
    role: CourseAssetRole = Field(index=True)
    original_name: str
    stored_path: str
    mime_type: str
    size_bytes: int
    sha256: str = Field(index=True)
    rights_status: RightsStatus = Field(default=RightsStatus.UNKNOWN, index=True)
    source_message_id: str = Field(default="", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EditingRecipe(SQLModel, table=True):
    __tablename__ = "editing_recipes"
    __table_args__ = (UniqueConstraint("course_id", "version", name="uq_course_recipe_version"),)

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    course_id: str = Field(foreign_key="courses.id", index=True)
    version: int = 1
    title: str
    summary: str = ""
    tutorial_asset_id: str | None = Field(default=None, foreign_key="course_assets.id", index=True)
    transcript_sha256: str = Field(default="", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EditingRule(SQLModel, table=True):
    __tablename__ = "editing_rules"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    recipe_id: str = Field(foreign_key="editing_recipes.id", index=True)
    category: str = Field(index=True)
    instruction: str
    evidence_text: str = ""
    confidence: float = 1.0
    source_asset_id: str = Field(foreign_key="course_assets.id", index=True)
    source_start_ms: int | None = None
    source_end_ms: int | None = None
    source_page: int | None = None
    sort_order: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MaterialShot(SQLModel, table=True):
    __tablename__ = "material_shots"
    __table_args__ = (
        UniqueConstraint("asset_id", "start_ms", "end_ms", name="uq_material_shot_range"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    asset_id: str = Field(foreign_key="course_assets.id", index=True)
    start_ms: int
    end_ms: int
    thumbnail_path: str = ""
    ocr_text: str = ""
    tags_json: str = "[]"
    embedding_json: str = "[]"
    phash: str = Field(default="", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CourseProcessingRun(SQLModel, table=True):
    __tablename__ = "course_processing_runs"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    course_id: str = Field(foreign_key="courses.id", index=True)
    state: str = Field(default="queued", index=True)
    error_code: str = ""
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None


class CourseEditJob(SQLModel, table=True):
    __tablename__ = "course_edit_jobs"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    course_id: str = Field(foreign_key="courses.id", index=True)
    recipe_id: str = Field(foreign_key="editing_recipes.id", index=True)
    task_id: str | None = Field(default=None, foreign_key="video_tasks.id", index=True)
    device_id: str | None = Field(default=None, foreign_key="delivery_devices.id", index=True)
    state: str = Field(default="queued", index=True)
    commercial: bool = True
    quality_status: str = "pending"
    review_skipped: bool = False
    handoff_status: str = "pending"
    error_code: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DeliveryDevice(SQLModel, table=True):
    __tablename__ = "delivery_devices"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name: str
    token_hash: str = Field(index=True, unique=True)
    active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_seen_at: datetime | None = None


class DevicePairingCode(SQLModel, table=True):
    __tablename__ = "device_pairing_codes"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    code_hash: str = Field(index=True, unique=True)
    expires_at: datetime
    used_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class VideoTask(SQLModel, table=True):
    __tablename__ = "video_tasks"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    title: str
    content_type: str
    rights_confirmed: bool = False
    status: TaskStatus = Field(default=TaskStatus.RECEIVED)
    source_type: str | None = None
    source_user: str | None = None
    source_conversation: str | None = None
    source_message_id: str | None = None
    deduplication_key: str | None = Field(default=None, index=True, unique=True)
    archived_at: datetime | None = Field(default=None, index=True)
    archive_reason: str | None = None
    delivery_state: DeliveryState | None = None
    delivery_provider_id: str | None = None
    delivered_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    materials: list["Material"] = Relationship(
        back_populates="task",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "lazy": "selectin"},
    )
    brief: Optional["TaskBrief"] = Relationship(
        back_populates="task",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "uselist": False},
    )
    production_settings: Optional["TaskProductionSettings"] = Relationship(
        back_populates="task",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "uselist": False},
    )
    voice_selection: Optional["TaskVoiceSelection"] = Relationship(
        back_populates="task",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "uselist": False},
    )

    @property
    def requirements_text(self) -> str:
        return self.brief.requirements_text if self.brief else ""

    @property
    def tutorial_text(self) -> str:
        return self.brief.tutorial_text if self.brief else ""

    @property
    def quality_profile(self) -> str:
        return self.production_settings.quality_profile if self.production_settings else "production"

    @property
    def cloud_processing_allowed(self) -> bool:
        return bool(self.production_settings and self.production_settings.cloud_processing_allowed)

    @property
    def reference_path(self) -> str | None:
        return self.production_settings.reference_path if self.production_settings else None

    @property
    def reference_name(self) -> str | None:
        return self.production_settings.reference_name if self.production_settings else None

    @property
    def reference_sha256(self) -> str | None:
        return self.production_settings.reference_sha256 if self.production_settings else None

    @property
    def voice_preset(self) -> str:
        return self.voice_selection.preset_id if self.voice_selection else "vivi-2"

    @property
    def voice_type(self) -> str:
        return self.voice_selection.voice_type if self.voice_selection else "zh_female_vv_uranus_bigtts"


class TaskBrief(SQLModel, table=True):
    __tablename__ = "task_briefs"

    task_id: str = Field(foreign_key="video_tasks.id", primary_key=True)
    requirements_text: str = ""
    tutorial_text: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    task: Optional[VideoTask] = Relationship(back_populates="brief")


class TaskProductionSettings(SQLModel, table=True):
    __tablename__ = "task_production_settings"

    task_id: str = Field(foreign_key="video_tasks.id", primary_key=True)
    quality_profile: str = "production"
    cloud_processing_allowed: bool = False
    reference_name: str | None = None
    reference_path: str | None = None
    reference_sha256: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    task: Optional[VideoTask] = Relationship(back_populates="production_settings")


class TaskVoiceSelection(SQLModel, table=True):
    __tablename__ = "task_voice_selections"

    task_id: str = Field(foreign_key="video_tasks.id", primary_key=True)
    preset_id: str = "vivi-2"
    voice_type: str = "zh_female_vv_uranus_bigtts"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    task: Optional[VideoTask] = Relationship(back_populates="voice_selection")


class Material(SQLModel, table=True):
    __tablename__ = "materials"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    task_id: str = Field(foreign_key="video_tasks.id", index=True)
    original_name: str
    stored_path: str
    mime_type: str
    size_bytes: int
    sha256: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    task: VideoTask | None = Relationship(back_populates="materials")


class LicensedAsset(SQLModel, table=True):
    __tablename__ = "licensed_assets"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    sha256: str = Field(index=True, unique=True)
    provider: str = Field(index=True)
    provider_asset_id: str = Field(default="", index=True)
    original_name: str
    stored_path: str
    mime_type: str = "video/mp4"
    size_bytes: int = 0
    width: int = 0
    height: int = 0
    duration_seconds: float = 0
    source_url: str = ""
    preview_url: str = ""
    creator_name: str = ""
    creator_url: str = ""
    license_url: str = ""
    rights_status: str = Field(default="authorized", index=True)
    rights_basis: str
    product_id: str = Field(default="", index=True)
    allowed_platforms_json: str = "[]"
    rights_expires_at: datetime | None = None
    attribution: str = ""
    search_text: str = ""
    use_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_used_at: datetime | None = None


class ReviewEvent(SQLModel, table=True):
    __tablename__ = "review_events"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    task_id: str = Field(foreign_key="video_tasks.id", index=True)
    decision: str
    comment: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TrendRecord(SQLModel, table=True):
    __tablename__ = "trend_records"
    __table_args__ = (UniqueConstraint("source", "keyword", "item_id", name="uq_trend_source_keyword_item"),)

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    source: str = Field(index=True)
    source_type: str = "public"
    keyword: str = Field(index=True)
    item_id: str = Field(index=True)
    title: str
    url: str
    digg_count: int = 0
    author: str = ""
    cover_url: str = ""
    high_quality_text: str = ""
    evidence: str
    published_at: datetime | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)


class AutomationSchedule(SQLModel, table=True):
    __tablename__ = "automation_schedules"

    id: str = Field(default="daily", primary_key=True)
    enabled: bool = True
    hour: int = 8
    minute: int = 30
    timezone: str = "Asia/Shanghai"
    keywords_json: str = "[]"
    last_run_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AutomationRun(SQLModel, table=True):
    __tablename__ = "automation_runs"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    status: str = "running"
    trigger: str = "manual"
    trend_status: str = "not_started"
    trend_records: int = 0
    processed_tasks: int = 0
    failed_tasks: int = 0
    warning: str = ""
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    detail: Optional["AutomationRunDetail"] = Relationship(
        back_populates="run",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "uselist": False},
    )

    @property
    def material_status(self) -> str:
        detail = self.__dict__.get("detail")
        if detail is not None:
            return detail.material_status
        return self.__dict__.get("_material_status", "not_recorded")

    @property
    def sourced_assets(self) -> int:
        detail = self.__dict__.get("detail")
        if detail is not None:
            return detail.sourced_assets
        return int(self.__dict__.get("_sourced_assets", 0))

    @property
    def created_task_ids(self) -> list[str]:
        detail = self.__dict__.get("detail")
        if detail is None:
            return list(self.__dict__.get("_created_task_ids", []))
        import json

        return list(json.loads(detail.created_task_ids_json))


class AutomationRunDetail(SQLModel, table=True):
    __tablename__ = "automation_run_details"

    run_id: str = Field(foreign_key="automation_runs.id", primary_key=True)
    material_status: str = "not_started"
    sourced_assets: int = 0
    created_task_ids_json: str = "[]"
    provider_summary_json: str = "{}"

    run: Optional[AutomationRun] = Relationship(back_populates="detail")


class CloudCredential(SQLModel, table=True):
    __tablename__ = "cloud_credentials"

    provider: str = Field(primary_key=True)
    access_key_id_masked: str = ""
    encrypted_access_key_id: str = ""
    encrypted_secret_access_key: str = ""
    permission_mode: str = "read_only"
    verified_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProviderCredential(SQLModel, table=True):
    __tablename__ = "provider_credentials"

    provider_id: str = Field(primary_key=True)
    encrypted_values_json: str = "{}"
    masked_values_json: str = "{}"
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UsageEvent(SQLModel, table=True):
    __tablename__ = "usage_events"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    task_id: str | None = Field(default=None, index=True)
    provider: str = Field(index=True)
    service: str = Field(index=True)
    metric: str = Field(index=True)
    quantity: float = 0
    unit: str = "requests"
    status: str = "succeeded"
    request_id: str = ""
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)


class UsageBudget(SQLModel, table=True):
    __tablename__ = "usage_budgets"

    id: str = Field(default="default", primary_key=True)
    asr_total_seconds: float = 0
    tts_total_characters: float = 0
    ark_monthly_tokens: float = 0
    warning_threshold_percent: float = 20
    critical_threshold_percent: float = 10
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class OfficialUsageSnapshot(SQLModel, table=True):
    __tablename__ = "official_usage_snapshots"

    kind: str = Field(primary_key=True)
    payload_json: str = "{}"
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error: str = ""
