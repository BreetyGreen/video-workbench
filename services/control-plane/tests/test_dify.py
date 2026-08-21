from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml

from app.adapters.dify import AnalysisOutputError, DifyClient
from app.config import Settings


def settings(**overrides) -> Settings:
    values = {
        "dify_base_url": "http://dify.test/v1",
        "dify_tutorial_api_key": "app-test-key",
        "dify_viral_api_key": "app-test-key",
    }
    values.update(overrides)
    return Settings(**values)


def transport_with_output(output: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer app-test-key"
        assert request.url.path == "/v1/workflows/run"
        return httpx.Response(200, json={"data": {"outputs": {"text": output}}})

    return httpx.MockTransport(handler)


def test_invalid_dify_json_fails_with_raw_response():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"workflow_run_id": "run-1", "total_tokens": 714, "elapsed_time": 10.3, "outputs": {"text": "not-json"}}})

    client = DifyClient(settings(), transport=httpx.MockTransport(handler))

    with pytest.raises(AnalysisOutputError) as error:
        client.analyze_tutorial({"text": "tutorial"})

    assert error.value.raw_response == "not-json"
    assert client.last_usage is not None
    assert client.last_usage.total_tokens == 714
    assert client.last_usage.workflow_run_id == "run-1"


def test_tutorial_analysis_validates_typed_recipe():
    output = json.dumps(
        {
            "hook_rules": ["首秒展示结果"],
            "target_duration_seconds": 28,
            "pacing": [{"from_second": 0, "to_second": 3, "instruction": "快速切镜"}],
            "track_layout": ["主视频", "字幕", "背景音乐"],
            "caption_style": "白字黑边，安全区内",
            "audio_rules": ["人声优先"],
            "prohibited_elements": ["水印"],
            "qa_thresholds": {"max_silence_seconds": 1.0, "max_black_seconds": 0.5},
        },
        ensure_ascii=False,
    )
    client = DifyClient(settings(), transport=transport_with_output(output))

    recipe = client.analyze_tutorial({"text": "tutorial"})

    assert recipe.target_duration_seconds == 28
    assert recipe.pacing[0].instruction == "快速切镜"


def test_viral_analysis_separates_evidence_and_copy_variants():
    output = json.dumps(
        {
            "summary": "结果前置的视频表现更集中",
            "patterns": ["前三秒给出冲突"],
            "evidence": [
                {
                    "metric": "点赞数",
                    "value": "120000",
                    "source_type": "public",
                    "source": "https://example.test/video/1",
                    "explanation": "公开页面可见指标",
                }
            ],
            "recommendations": ["保留真实素材原声"],
            "publish_copy": [
                {
                    "title": f"标题{i}",
                    "body": f"正文{i}",
                    "topics": ["宠物", "日常"],
                    "rationale": "对应内容主题",
                }
                for i in range(1, 4)
            ],
        },
        ensure_ascii=False,
    )
    client = DifyClient(settings(), transport=transport_with_output(output))

    analysis = client.analyze_viral({"trend_records": []})

    assert analysis.evidence[0].source_type == "public"
    assert len(analysis.publish_copy) == 3


def test_missing_api_key_reports_not_configured_without_request():
    client = DifyClient(settings(dify_tutorial_api_key="", dify_viral_api_key=""))

    assert client.status() == {
        "status": "not_configured",
        "reason": "missing_tutorial_and_viral_api_key",
    }
    with pytest.raises(RuntimeError, match="not configured"):
        client.analyze_tutorial({"text": "tutorial"})


@pytest.mark.parametrize("filename", ["tutorial-analysis.yml", "viral-analysis.yml"])
def test_dify_dsl_has_importable_workflow_shape(filename: str):
    project_root = Path(__file__).resolve().parents[3]
    payload = yaml.safe_load((project_root / "workflows" / "dify" / filename).read_text(encoding="utf-8"))

    assert payload["kind"] == "app"
    assert payload["version"] == "0.3.0"
    assert payload["app"]["mode"] == "workflow"
    node_types = {node["data"]["type"] for node in payload["workflow"]["graph"]["nodes"]}
    assert node_types == {"start", "llm", "end"}
    assert len(payload["workflow"]["graph"]["edges"]) == 2
    llm_node = next(node for node in payload["workflow"]["graph"]["nodes"] if node["data"]["type"] == "llm")
    assert llm_node["data"]["model"]["name"] == "doubao-seed-2-0-pro-260215"
    assert llm_node["data"]["model"]["completion_params"]["thinking"] == "disabled"
