from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VIDEO_WORKBENCH_",
        env_file=".env",
        extra="ignore",
    )

    data_dir: Path = Path("data/control-plane")
    database_url: str = "sqlite:///data/control-plane/control-plane.db"
    usage_secret_master_key: str = ""
    dify_base_url: str = ""
    dify_tutorial_api_key: str = ""
    dify_viral_api_key: str = ""
    dify_timeout_seconds: float = 90.0
    dingtalk_client_id: str = ""
    dingtalk_client_secret: str = ""
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    transcription_enabled: bool = True
    whisper_model: str = "small"
    whisper_preview_model: str = ""
    whisper_quality_model: str = "large-v3"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_cpu_threads: int = 0
    volcano_asr_api_key: str = ""
    volcano_asr_app_key: str = ""
    volcano_asr_access_key: str = ""
    volcano_asr_resource_id: str = "volc.bigasr.auc_turbo"
    volcano_asr_endpoint: str = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash"
    volcano_asr_timeout_seconds: float = 180.0
    volcano_tts_api_key: str = ""
    volcano_tts_resource_id: str = "seed-tts-2.0"
    volcano_tts_endpoint: str = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
    volcano_tts_voice_type: str = "zh_female_vv_uranus_bigtts"
    volcano_tts_timeout_seconds: float = 90.0
    ocr_enabled: bool = True
    scene_threshold: float = 0.25
    silence_threshold_db: float = -42.0
    silence_minimum_seconds: float = 0.8
    keyframe_limit: int = 12
    render_preset: str = "medium"
    render_crf: int = 23
    quality_max_black_seconds: float = 0.5
    quality_max_silence_seconds: float = 1.5
    quality_duration_tolerance_seconds: float = 0.25
    cover_font_path: Path | None = None
    douyin_client_key: str = ""
    douyin_client_secret: str = ""
    douyin_device_id: int = 0
    douyin_open_id: str = ""
    douyin_access_token: str = ""
    pexels_api_key: str = ""
    pexels_api_base_url: str = "https://api.pexels.com"
    pexels_timeout_seconds: float = 60.0
    pexels_max_download_bytes: int = 262_144_000
    pixabay_api_key: str = ""
    pixabay_api_base_url: str = "https://pixabay.com"
    pixabay_timeout_seconds: float = 60.0
    automation_enabled: bool = True
    automation_scheduler_enabled: bool = True
    automation_hour: int = 8
    automation_minute: int = 30
    automation_timezone: str = "Asia/Shanghai"
    automation_keywords: str = "宠物,萌宠"
    automation_poll_seconds: int = 60
    automation_auto_create_tasks: bool = True
    automation_task_limit: int = 1
    automation_material_count: int = 3
    public_trend_web_enabled: bool = True
    public_trend_web_endpoint: str = "https://html.duckduckgo.com/html/"
    public_trend_web_timeout_seconds: float = 20.0
    seedance_api_key: str = ""
    seedance_model: str = ""
    seedance_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"

    @property
    def material_dir(self) -> Path:
        return self.data_dir / "materials"

    @property
    def artifact_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def model_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def library_dir(self) -> Path:
        return self.data_dir / "licensed-library"
