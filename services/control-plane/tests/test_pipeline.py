from __future__ import annotations

import json
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.dify import DifyClient
from app.adapters.volcano_tts import TTSResult
from app.config import Settings
from app.main import create_app
from app.services.pipeline_service import PipelineService


def test_product_narration_is_complete_but_bounded_for_a_22_second_video():
    task = SimpleNamespace(
        title="奶油博美幼犬展示｜真实画面介绍",
        content_type="萌宠商品介绍",
        requirements_text="商品介绍风格",
        tutorial_text="四段式旁白覆盖全片",
    )

    narration = PipelineService._narration_text(task)

    assert 70 <= len(narration) <= 105
    assert narration.count("。") == 4
    assert narration.endswith("。")


def test_product_narration_uses_content_type_and_fits_the_actual_timeline():
    task = SimpleNamespace(
        title="做一个25秒宠物除毛梳商品介绍",
        content_type="商品介绍",
        requirements_text="使用真实宠物素材，不夸大效果",
        tutorial_text="结果前置",
    )

    narration = PipelineService._narration_text(task, target_seconds=18.5)

    assert 60 <= len(narration) <= 88
    assert "除毛梳" in narration
    assert "真实试用" in narration
    assert "做一个25秒" not in narration


def test_hat_product_narration_never_falls_back_to_pet_brush_copy():
    task = SimpleNamespace(
        title="轻量遮阳帽｜三场景真实素材商品介绍",
        content_type="商品介绍",
        requirements_text="突出修饰脸型、遮阳、轻便易搭",
        tutorial_text="前三秒上身钩子",
    )

    narration = PipelineService._narration_text(task, target_seconds=24)

    assert "帽" in narration
    assert "遮阳" in narration
    assert "除毛梳" not in narration
    assert "宠物" not in narration


def test_general_narration_fills_a_short_form_timeline_without_date_padding():
    task = SimpleNamespace(
        title="萌宠治愈瞬间",
        content_type="热点改编",
        requirements_text="前三秒结果前置，旁白覆盖主体段落",
        tutorial_text="",
    )

    narration = PipelineService._narration_text(task, target_seconds=17.4)

    assert 72 <= len(narration) <= 82
    assert narration.endswith("。")
    assert "收藏" in narration


def test_voiceover_is_locally_time_fitted_without_another_cloud_call(
    tmp_path: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
):
    source = tmp_path / "long-voice.mp3"
    subprocess.run(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=24000:d=3",
            "-y",
            str(source),
        ],
        check=True,
    )
    settings = Settings(data_dir=tmp_path / "data", ffmpeg_bin=ffmpeg_bin, ffprobe_bin=ffprobe_bin)
    pipeline = PipelineService(settings)
    generated = TTSResult(
        path=source,
        duration_seconds=3,
        voice_type="zh_female_vv_uranus_bigtts",
        character_count=30,
    )

    fitted, speed_factor = pipeline._fit_voiceover(generated, target_seconds=2)

    assert fitted.path != source
    assert fitted.path.is_file()
    assert 1.85 <= fitted.duration_seconds <= 2.02
    assert speed_factor > 1
    assert fitted.character_count == generated.character_count


def test_short_voiceover_is_slowed_locally_to_cover_the_timeline(
    tmp_path: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
):
    source = tmp_path / "short-voice.mp3"
    subprocess.run(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=24000:d=3",
            "-y",
            str(source),
        ],
        check=True,
    )
    pipeline = PipelineService(
        Settings(data_dir=tmp_path / "data", ffmpeg_bin=ffmpeg_bin, ffprobe_bin=ffprobe_bin)
    )
    generated = TTSResult(
        path=source,
        duration_seconds=3,
        voice_type="zh_female_vv_uranus_bigtts",
        character_count=24,
    )

    fitted, speed_factor = pipeline._fit_voiceover(generated, target_seconds=4)

    assert fitted.path.is_file()
    assert 3.55 <= fitted.duration_seconds <= 3.8
    assert 0.5 <= speed_factor < 1


def test_matching_pipeline_voiceover_is_reused_on_retry(
    tmp_path: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
):
    analysis_dir = tmp_path / "analysis"
    analysis_dir.mkdir()
    source = analysis_dir / "voiceover.mp3"
    subprocess.run(
        [ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:d=1", "-y", str(source)],
        check=True,
    )
    (analysis_dir / "audio-routing.json").write_text(
        json.dumps(
            {
                "narration_text": "重试不应该重复调用云端。",
                "voice_type": "zh_female_vv_uranus_bigtts",
                "voiceover_generated_path": str(source),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    settings = Settings(data_dir=tmp_path / "data", ffmpeg_bin=ffmpeg_bin, ffprobe_bin=ffprobe_bin)

    cached = PipelineService(settings)._cached_voiceover(
        analysis_dir,
        narration_text="重试不应该重复调用云端。",
        voice_type="zh_female_vv_uranus_bigtts",
    )

    assert cached is not None
    assert cached.path == source.resolve()
    assert cached.duration_seconds == pytest.approx(1, abs=0.08)
    assert cached.character_count == len("重试不应该重复调用云端。")


@pytest.fixture
def pipeline_client(tmp_path: Path, ffmpeg_bin: str, ffprobe_bin: str) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'pipeline.db').as_posix()}",
        ffmpeg_bin=ffmpeg_bin,
        ffprobe_bin=ffprobe_bin,
        dify_base_url="",
        dify_tutorial_api_key="",
        dify_viral_api_key="",
        dingtalk_client_id="",
        dingtalk_client_secret="",
        volcano_asr_api_key="",
        volcano_asr_app_key="",
        volcano_asr_access_key="",
        douyin_client_key="",
        douyin_client_secret="",
        douyin_device_id=0,
        automation_enabled=False,
        transcription_enabled=False,
        ocr_enabled=False,
        render_preset="ultrafast",
    )
    with TestClient(create_app(settings)) as client:
        yield client


def test_local_pipeline_creates_preview_draft_and_review_page(
    pipeline_client: TestClient,
    ffmpeg_fixture: Path,
):
    created = pipeline_client.post(
        "/api/tasks",
        data={"title": "全链路样例", "content_type": "pet", "rights_confirmed": "true"},
        files=[("files", ("fixture.mp4", ffmpeg_fixture.read_bytes(), "video/mp4"))],
    ).json()

    response = pipeline_client.post(f"/api/tasks/{created['id']}/process")

    assert response.status_code == 200
    assert response.json()["status"] == "reviewing"
    artifact_dir = pipeline_client.app.state.settings.artifact_dir / created["id"]
    assert (artifact_dir / "preview.mp4").exists()
    assert (artifact_dir / "preview.json").exists()
    assert (artifact_dir / "draft.zip").exists()
    assert (artifact_dir / "review.json").exists()
    assert (artifact_dir / "quality-report.json").exists()
    quality = json.loads((artifact_dir / "quality-report.json").read_text(encoding="utf-8"))
    assert quality["status"] in {"pass", "warn"}
    assert quality["blocking_failures"] == []
    with zipfile.ZipFile(artifact_dir / "draft.zip") as archive:
        assert any(name.endswith("draft_info.json") for name in archive.namelist())

    page = pipeline_client.get(f"/review/{created['id']}")
    assert page.status_code == 200
    assert "全链路样例" in page.text
    assert "Dify 尚未配置" in page.text


def test_integration_status_is_explicit_when_credentials_are_missing(pipeline_client: TestClient):
    response = pipeline_client.get("/api/integrations/status")

    assert response.status_code == 200
    assert response.json()["dify"]["status"] == "not_configured"
    assert response.json()["dingtalk"]["status"] == "not_configured"
    assert response.json()["asr"]["status"] == "partially_configured"
    assert response.json()["tts"]["status"] == "not_configured"
    assert response.json()["reference_intelligence"]["status"] == "configured"
    assert response.json()["public_trends"]["status"] == "disabled"
    assert response.json()["pixabay"]["status"] == "not_configured"
    assert response.json()["seedance"]["status"] == "not_configured"
    assert response.json()["douyin_delivery"]["status"] == "oauth_required"


def test_pipeline_generates_conditional_voiceover_and_records_audio_route(
    tmp_path: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
    ffmpeg_fixture: Path,
):
    class FakeTTS:
        configured = True
        voice_type = "zh_female_vv_uranus_bigtts"

        def synthesize(self, text: str, output: Path) -> TTSResult:
            assert "萌宠" in text
            subprocess.run(
                [
                    ffmpeg_bin,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=24000:d=1",
                    "-y",
                    str(output.with_suffix(".wav")),
                ],
                check=True,
            )
            return TTSResult(
                path=output.with_suffix(".wav").resolve(),
                duration_seconds=1,
                voice_type=self.voice_type,
                character_count=len(text.strip()),
            )

    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'tts-pipeline.db').as_posix()}",
        ffmpeg_bin=ffmpeg_bin,
        ffprobe_bin=ffprobe_bin,
        automation_enabled=False,
        transcription_enabled=False,
        ocr_enabled=False,
        render_preset="ultrafast",
    )
    with TestClient(create_app(settings, tts_client=FakeTTS())) as client:
        created = client.post(
            "/api/tasks",
            data={
                "title": "萌宠反差日常",
                "content_type": "萌宠",
                "requirements_text": "治愈、轻反差，不虚构具体事件。",
                "rights_confirmed": "true",
            },
            files=[("files", ("fixture.mp4", ffmpeg_fixture.read_bytes(), "video/mp4"))],
        ).json()

        response = client.post(f"/api/tasks/{created['id']}/process")

        assert response.status_code == 200, response.text
        artifact_dir = settings.artifact_dir / created["id"]
        review = json.loads((artifact_dir / "review.json").read_text(encoding="utf-8"))
        timeline = json.loads((artifact_dir / "edit-timeline.json").read_text(encoding="utf-8"))
        assert review["audio_route"]["mode"] == "narration"
        assert review["audio_route"]["voice_type"] == "zh_female_vv_uranus_bigtts"
        assert review["audio_route"]["voiceover_used"] is True
        assert 5 <= len(review["audio_route"]["narration_text"]) <= 30
        assert "萌宠" in review["audio_route"]["narration_text"]
        assert timeline["audio"]["voiceover_path"]
        assert (artifact_dir / "analysis" / "audio-routing.json").is_file()
        manifest = client.get(f"/api/tasks/{created['id']}/manifest").json()
        assert manifest["audio_route"]["mode"] == "narration"
        assert manifest["audio_route"]["voiceover_used"] is True
        usage = client.get(f"/api/tasks/{created['id']}/usage").json()
        assert usage["totals"]["tts_characters"] > 0
        assert usage["totals"]["voiceover_seconds"] == 1


def test_pipeline_applies_tutorial_recipe_and_viral_copy(
    tmp_path: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
    ffmpeg_fixture: Path,
):
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        if request.headers["authorization"] == "Bearer tutorial-key":
            output = {
                "hook_rules": ["首秒先展示小狗冲向镜头"],
                "target_duration_seconds": 1,
                "pacing": [{"from_second": 0, "to_second": 1, "instruction": "快速开场"}],
                "track_layout": ["主视频", "大字标题"],
                "caption_style": "白字黑边",
                "audio_rules": ["保留真实原声"],
                "prohibited_elements": ["第三方水印"],
                "qa_thresholds": {"max_silence_seconds": 1.0, "max_black_seconds": 0.5},
            }
        else:
            output = {
                "summary": "公开高赞样本常用结果前置",
                "patterns": ["结果前置"],
                "evidence": [
                    {
                        "metric": "点赞数",
                        "value": "12000",
                        "source_type": "public",
                        "source": "https://example.test/video/1",
                        "explanation": "来自已导入的公开页面指标",
                    }
                ],
                "recommendations": ["开头一秒展示动作"],
                "publish_copy": [
                    {
                        "title": f"Dify 标题{i}",
                        "body": f"Dify 正文{i}",
                        "topics": ["宠物", "小狗"],
                        "rationale": "对应公开样本",
                    }
                    for i in range(1, 4)
                ],
            }
        return httpx.Response(
            200,
            json={
                "data": {
                    "workflow_run_id": f"run-{len(requests)}",
                    "input_tokens": 120,
                    "output_tokens": 80,
                    "total_tokens": 200,
                    "elapsed_time": 1.2,
                    "outputs": {"text": json.dumps(output, ensure_ascii=False)},
                }
            },
        )

    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'dify-pipeline.db').as_posix()}",
        ffmpeg_bin=ffmpeg_bin,
        ffprobe_bin=ffprobe_bin,
        dify_base_url="http://dify.test/v1",
        dify_tutorial_api_key="tutorial-key",
        dify_viral_api_key="viral-key",
        volcano_tts_api_key="",
        volcano_asr_api_key="",
        automation_enabled=False,
        transcription_enabled=False,
        ocr_enabled=False,
        render_preset="ultrafast",
    )
    dify = DifyClient(settings, transport=httpx.MockTransport(handler))
    with TestClient(create_app(settings, dify_client=dify)) as client:
        trend = client.post(
            "/api/trends/import",
            json={
                "records": [
                    {
                        "source": "manual",
                        "keyword": "宠物",
                        "item_id": "video-1",
                        "title": "公开样本",
                        "url": "https://example.test/video/1",
                        "digg_count": 12000,
                        "author": "示例作者",
                        "captured_at": datetime.now(UTC).isoformat(),
                        "evidence": "人工核对的公开页面指标",
                    }
                ]
            },
        )
        assert trend.status_code == 200
        created = client.post(
            "/api/tasks",
            data={
                "title": "教程驱动样例",
                "content_type": "宠物",
                "rights_confirmed": "true",
                "requirements_text": "竖屏，节奏快，保留原声",
                "tutorial_text": "开头一秒展示结果，然后快速切镜。",
            },
            files=[("files", ("fixture.mp4", ffmpeg_fixture.read_bytes(), "video/mp4"))],
        ).json()

        response = client.post(f"/api/tasks/{created['id']}/process")

        assert response.status_code == 200
        assert response.json()["requirements_text"] == "竖屏，节奏快，保留原声"
        artifact_dir = settings.artifact_dir / created["id"]
        recipe = json.loads((artifact_dir / "analysis" / "edit-recipe.json").read_text(encoding="utf-8"))
        viral = json.loads((artifact_dir / "analysis" / "viral-analysis.json").read_text(encoding="utf-8"))
        review = json.loads((artifact_dir / "review.json").read_text(encoding="utf-8"))
        assert recipe["target_duration_seconds"] == 1
        assert viral["summary"] == "公开高赞样本常用结果前置"
        assert review["publish_copy"][0]["title"] == "Dify 标题1"
        assert any("Dify 教程配方" in item for item in review["evidence"])
        assert requests[0]["inputs"]["tutorial_text"] == "开头一秒展示结果，然后快速切镜。"
        assert "12000" in requests[1]["inputs"]["trend_records"]
        usage = client.get(f"/api/tasks/{created['id']}/usage").json()
        assert usage["totals"]["input_tokens"] == 240
        assert usage["totals"]["output_tokens"] == 160
        assert usage["totals"]["total_tokens"] == 400
        assert {event["request_id"] for event in usage["events"]} == {"run-1", "run-2"}


def test_pipeline_uses_all_video_materials_for_one_timeline_and_draft(
    pipeline_client: TestClient,
    ffmpeg_fixture: Path,
):
    created = pipeline_client.post(
        "/api/tasks",
        data={"title": "多素材成片", "content_type": "pet", "rights_confirmed": "true"},
        files=[
            ("files", ("camera-a.mp4", ffmpeg_fixture.read_bytes(), "video/mp4")),
            ("files", ("camera-b.mp4", ffmpeg_fixture.read_bytes(), "video/mp4")),
        ],
    ).json()

    response = pipeline_client.post(f"/api/tasks/{created['id']}/process")

    assert response.status_code == 200, response.text
    artifact_dir = pipeline_client.app.state.settings.artifact_dir / created["id"]
    analyses = json.loads((artifact_dir / "analysis" / "media-analysis.json").read_text("utf-8"))
    timeline = json.loads((artifact_dir / "edit-timeline.json").read_text("utf-8"))
    report = json.loads((artifact_dir / "render-report.json").read_text("utf-8"))
    assert len(analyses) == 2
    assert timeline["source_count"] == 2
    assert {clip["material_id"] for clip in timeline["clips"]} == {
        created["materials"][0]["id"],
        created["materials"][1]["id"],
    }
    assert report["source_count"] == 2
    assert (artifact_dir / "captions.srt").is_file()
    assert (artifact_dir / "cover.jpg").is_file()
    with zipfile.ZipFile(artifact_dir / "draft.zip") as archive:
        draft_name = next(name for name in archive.namelist() if name.endswith("draft_info.json"))
        draft = json.loads(archive.read(draft_name))
        video_track = next(track for track in draft["tracks"] if track["type"] == "video")
        assert len(video_track["segments"]) == len(timeline["clips"])


def test_pipeline_uses_separate_reference_video_to_guide_timeline(
    pipeline_client: TestClient,
    ffmpeg_fixture: Path,
):
    created = pipeline_client.post(
        "/api/tasks",
        data={
            "title": "参考片驱动成片",
            "content_type": "pet",
            "rights_confirmed": "true",
            "quality_profile": "fast_preview",
        },
        files=[
            ("files", ("source.mp4", ffmpeg_fixture.read_bytes(), "video/mp4")),
            ("reference_file", ("reference.mp4", ffmpeg_fixture.read_bytes(), "video/mp4")),
        ],
    ).json()

    response = pipeline_client.post(f"/api/tasks/{created['id']}/process")

    assert response.status_code == 200, response.text
    artifact_dir = pipeline_client.app.state.settings.artifact_dir / created["id"]
    reference = json.loads(
        (artifact_dir / "analysis" / "reference-video-brief.json").read_text(encoding="utf-8")
    )
    timeline = json.loads((artifact_dir / "edit-timeline.json").read_text(encoding="utf-8"))
    review = json.loads((artifact_dir / "review.json").read_text(encoding="utf-8"))
    assert reference["source_name"] == "reference.mp4"
    assert reference["provider"] == "local_structural"
    assert timeline["engine"] == "reference_guided"
    assert review["production_profile"]["quality_profile"] == "fast_preview"
    assert review["reference_brief"]["source_name"] == "reference.mp4"
    assert review["quality_report"]["blocking_failures"] == []
