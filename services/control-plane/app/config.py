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
    dify_tutorial_workflow_revision: str = ""
    dify_viral_api_key: str = ""
    dify_timeout_seconds: float = 90.0
    # Director (shot plan + narration) through any OpenAI-compatible chat endpoint,
    # e.g. Alibaba DashScope compatible-mode. Takes precedence over Dify when set.
    director_base_url: str = ""
    director_api_key: str = ""
    director_model: str = "qwen3-vl-plus"
    director_timeout_seconds: float = 240.0
    director_max_output_tokens: int = 4096
    director_disable_thinking: bool = True
    # Full tutorial-video study through the director endpoint (video input, chunked).
    tutorial_study_enabled: bool = True
    tutorial_study_model: str = ""
    tutorial_study_chunk_seconds: int = 120
    tutorial_study_fps: float = 0.5
    tutorial_study_concurrency: int = 3
    tutorial_study_max_chunk_bytes: int = 9_000_000
    tutorial_study_max_output_tokens: int = 6144
    dingtalk_client_id: str = ""
    dingtalk_client_secret: str = ""
    course_max_file_bytes: int = 500 * 1024 * 1024
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
    # Speech provider: "auto" picks DashScope when its key/base URL are set, else Volcano.
    speech_provider: str = "auto"
    dashscope_api_key: str = ""
    dashscope_base_url: str = ""
    dashscope_asr_model: str = "paraformer-v2"
    dashscope_asr_timeout_seconds: float = 900.0
    dashscope_tts_model: str = "qwen3-tts-flash"
    dashscope_tts_voice: str = "Cherry"
    # Optional delivery instruction; requires an instruction-capable model such as qwen3-tts-instruct-flash.
    dashscope_tts_instructions: str = ""
    dashscope_tts_timeout_seconds: float = 120.0
    # "qwen" = Qwen3-TTS HTTP models; "cosyvoice" = CosyVoice v2 (DashScope SDK, WebSocket), the more
    # natural-sounding Chinese voices such as longxiaochun_v2.
    dashscope_tts_engine: str = "qwen"
    dashscope_cosyvoice_model: str = "cosyvoice-v2"
    dashscope_cosyvoice_voice: str = "longxiaochun_v2"
    dashscope_cosyvoice_speech_rate: float = 1.0
    # Caption presentation (ASS, 1080x1920 canvas)
    caption_font_name: str = "Microsoft YaHei"
    caption_font_size: int = 90
    caption_outline: int = 6
    caption_title_font_size: int = 150
    # "花字" look: highlighted punch words (RGB hex), drop shadow depth, and a pop-in
    # entrance on every cue (ASS scale animation; Jianying 弹入/放大 intro).
    caption_highlight_color: str = "FFE500"
    caption_shadow: int = 4
    caption_pop_in: bool = True
    # Narration claim guard: comma-separated terms a product narration must never contain
    # (price hints, unverifiable health/ingredient claims). One director retry, then fallback.
    prohibited_narration_terms: str = (
        "划算,便宜,性价比,优惠,折扣,限时,秒杀,包邮,无糖,0糖,零糖,低糖,无添加,零添加,纯天然,"
        "降火,清热,去火,解暑,祛湿,助消化,减肥,瘦身,美白,治疗,疗效,功效,排毒"
    )
    ocr_enabled: bool = True
    scene_threshold: float = 0.25
    silence_threshold_db: float = -42.0
    silence_minimum_seconds: float = 0.8
    keyframe_limit: int = 12
    render_preset: str = "medium"
    render_timeout_seconds: float = 1800.0
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
    def dashscope_speech_selected(self) -> bool:
        configured = bool(self.dashscope_api_key.strip() and self.dashscope_base_url.strip())
        provider = self.speech_provider.strip().lower()
        return provider == "dashscope" or (provider == "auto" and configured)

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
