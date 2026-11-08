from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
import yaml
from PIL import Image

from app.adapters.dify import AnalysisOutputError
from app.adapters.openai_compatible_director import (
    DIRECTOR_SYSTEM_PROMPT,
    OpenAICompatibleDirectorClient,
    extract_json_object,
    prompt_revision,
)
from app.config import Settings

RECIPE = {
    "hook_rules": ["首秒倒饮料"],
    "target_duration_seconds": 20,
    "pacing": [{"from_second": 0, "to_second": 20, "instruction": "1.2秒一镜"}],
    "track_layout": ["视频", "旁白", "字幕", "音乐"],
    "caption_style": "上方安全区白字黑边",
    "audio_rules": ["轻音乐不盖旁白"],
    "prohibited_elements": ["功效断言"],
    "qa_thresholds": {"max_silence_seconds": 1.0, "max_black_seconds": 0.5},
    "director_plan": {
        "version": 1,
        "beats": [
            {"purpose": "hook", "narration": "下午犯困先来一口", "material_id": "m1",
             "source_start_seconds": 1.0, "source_end_seconds": 2.2, "rationale": "倒饮料"},
            {"purpose": "closing", "narration": "从这杯开始", "material_id": "m2",
             "source_start_seconds": 0.5, "source_end_seconds": 1.9, "rationale": "杯瓶同框"},
        ],
    },
}


def settings(**overrides) -> Settings:
    values = {"director_base_url": "http://relay.test/compatible-mode/v1", "director_api_key": "sk-test",
              "director_model": "qwen3-vl-plus"}
    values.update(overrides)
    return Settings(**values)


def reply(text: str, *, usage: dict | None = None) -> httpx.Response:
    return httpx.Response(200, json={"id": "chatcmpl-1", "choices": [{"message": {"role": "assistant", "content": text}}],
                                     "usage": usage or {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160}})


def make_image(path: Path) -> Path:
    Image.new("RGB", (64, 64), "green").save(path, format="JPEG")
    return path


def test_prompt_matches_published_dify_workflow():
    document = yaml.safe_load(Path("workflows/dify/tutorial-analysis.yml").read_text(encoding="utf-8"))
    nodes = document["workflow"]["graph"]["nodes"]
    llm = next(node for node in nodes if node["data"].get("type") == "llm")
    system = next(item["text"] for item in llm["data"]["prompt_template"] if item["role"] == "system")
    assert system.strip() == DIRECTOR_SYSTEM_PROMPT.strip()


def test_director_sends_text_and_images_and_records_usage(tmp_path: Path):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return reply(json.dumps(RECIPE, ensure_ascii=False))

    client = OpenAICompatibleDirectorClient(settings(), transport=httpx.MockTransport(handler))
    frame = make_image(tmp_path / "frame.jpg")
    recipe = client.analyze_tutorial(
        {"tutorial_text": "先倒饮料", "transcript": "", "frame_descriptions": "{}", "content_category": "商品介绍"},
        image_paths=[frame],
    )

    assert seen["auth"] == "Bearer sk-test"
    assert seen["path"] == "/compatible-mode/v1/chat/completions"
    body = seen["body"]
    assert body["model"] == "qwen3-vl-plus"
    assert body["enable_thinking"] is False
    assert body["messages"][0] == {"role": "system", "content": DIRECTOR_SYSTEM_PROMPT}
    parts = body["messages"][1]["content"]
    assert parts[0]["type"] == "text" and "类目：商品介绍" in parts[0]["text"] and "教程：先倒饮料" in parts[0]["text"]
    assert parts[1] == {"type": "text", "text": "image_index 1"}
    assert parts[2]["type"] == "image_url"
    assert parts[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert base64.b64decode(parts[2]["image_url"]["url"].split(",", 1)[1]) == frame.read_bytes()
    assert recipe.director_plan is not None and recipe.director_plan.beats[0].purpose == "hook"
    assert client.last_usage is not None
    assert (client.last_usage.input_tokens, client.last_usage.output_tokens, client.last_usage.total_tokens) == (120, 40, 160)
    assert client.last_usage.workflow_run_id == "chatcmpl-1"


def test_fenced_or_prosed_json_is_still_parsed():
    text = "好的，结果如下：\n```json\n" + json.dumps(RECIPE, ensure_ascii=False) + "\n```\n以上。"
    client = OpenAICompatibleDirectorClient(settings(), transport=httpx.MockTransport(lambda _: reply(text)))
    recipe = client.analyze_tutorial({"tutorial_text": "x", "content_category": "商品介绍"})
    assert recipe.target_duration_seconds == 20
    assert extract_json_object('前言 {"a": 1} 后记') == '{"a": 1}'


def test_invalid_reply_raises_with_raw_and_usage():
    client = OpenAICompatibleDirectorClient(settings(), transport=httpx.MockTransport(lambda _: reply("我看不懂素材")))
    with pytest.raises(AnalysisOutputError) as error:
        client.analyze_tutorial({"tutorial_text": "x", "content_category": "商品介绍"})
    assert error.value.raw_response == "我看不懂素材"
    assert client.last_usage is not None and client.last_usage.total_tokens == 160


def test_unconfigured_client_never_sends_requests():
    calls = []
    client = OpenAICompatibleDirectorClient(settings(director_api_key=""),
                                            transport=httpx.MockTransport(lambda r: calls.append(r) or reply("{}")))
    assert client.configured is False
    assert client.status() == {"status": "not_configured", "reason": "missing_api_key"}
    with pytest.raises(RuntimeError):
        client.analyze_tutorial({"tutorial_text": "x"})
    assert calls == []


def test_image_limits_are_enforced_before_any_request(tmp_path: Path):
    calls = []
    client = OpenAICompatibleDirectorClient(settings(), transport=httpx.MockTransport(lambda r: calls.append(r) or reply("{}")))
    frames = [make_image(tmp_path / f"f{i}.jpg") for i in range(9)]
    with pytest.raises(ValueError):
        client.analyze_tutorial({"tutorial_text": "x"}, image_paths=frames)
    assert calls == []


def test_revision_changes_with_model_or_prompt():
    assert prompt_revision("qwen3-vl-plus") != prompt_revision("qwen-vl-max")
    assert prompt_revision("qwen3-vl-plus").startswith("openai_compatible:qwen3-vl-plus:")


def test_pipeline_prefers_configured_director_over_dify(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace
    from app.services.pipeline_service import PipelineService
    from app.schemas.analysis import EditRecipe

    recipe = EditRecipe.model_validate({**RECIPE, "director_plan": None})  # no materials in this unit test
    dify_calls, director_calls, usage = [], [], []
    dify = SimpleNamespace(analyze_tutorial=lambda *a, **kw: dify_calls.append(1) or recipe, last_usage=None)
    director = SimpleNamespace(
        configured=True, model="qwen3-vl-plus", endpoint="http://relay.test#qwen3-vl-plus",
        credential_scope="scope", revision=prompt_revision("qwen3-vl-plus"),
        analyze_tutorial=lambda *a, **kw: director_calls.append(kw) or recipe,
        last_usage=SimpleNamespace(workflow_run_id="chatcmpl-9", input_tokens=10, output_tokens=5, total_tokens=15,
                                   elapsed_time=0, status="succeeded"),
    )
    pipeline = PipelineService(Settings(data_dir=tmp_path, dify_base_url="http://dify.test/v1",
                                        dify_tutorial_api_key="app-key"), dify=dify, director=director)
    monkeypatch.setattr(pipeline, "_record_usage", lambda *a, **kw: usage.append(kw))
    task = SimpleNamespace(id="t1", tutorial_text="教程", cloud_processing_allowed=True, requirements_text="看包装",
                           content_type="商品介绍", materials=[])
    evidence, warnings = [], []
    result = pipeline._analyze_tutorial(None, task, [], tmp_path, evidence, warnings)

    assert result == recipe
    assert dify_calls == [] and len(director_calls) == 1
    assert {item["provider"] for item in usage} == {"openai_compatible"}
    assert all(item["metadata"]["model"] == "qwen3-vl-plus" for item in usage)
    report = json.loads((tmp_path / "visual-input-evidence.json").read_text(encoding="utf-8"))
    assert report["director_provider"] == "openai_compatible" and report["director_model"] == "qwen3-vl-plus"
    assert report["workflow_revision"].startswith("openai_compatible:qwen3-vl-plus:")
    assert any("导演模型 qwen3-vl-plus" in item for item in evidence)


def test_bare_beat_list_and_extra_beat_keys_are_normalized():
    from app.adapters.openai_compatible_director import normalize_recipe_payload

    drifted = {**RECIPE, "version": 1, "director_plan": [
        {**RECIPE["director_plan"]["beats"][0], "purpose": "Hook", "confidence": 0.9},
        RECIPE["director_plan"]["beats"][1],
    ]}
    client = OpenAICompatibleDirectorClient(settings(), transport=httpx.MockTransport(
        lambda _: reply(json.dumps(drifted, ensure_ascii=False))))
    recipe = client.analyze_tutorial({"tutorial_text": "x", "content_category": "商品介绍"})
    assert recipe.director_plan is not None
    assert [beat.purpose for beat in recipe.director_plan.beats] == ["hook", "closing"]
    assert normalize_recipe_payload({"director_plan": None})["director_plan"] is None
    assert normalize_recipe_payload("not-a-dict") == "not-a-dict"


def test_unknown_purposes_and_bookends_are_normalized():
    from app.adapters.openai_compatible_director import normalize_recipe_payload

    beat = RECIPE["director_plan"]["beats"][0]
    drifted = {**RECIPE, "director_plan": {"version": 1, "beats": [
        {**beat, "purpose": "identity"}, {**beat, "purpose": "spec"}, {**beat, "purpose": "closing"},
        {**beat, "purpose": "mystery"}, {**beat, "purpose": "hook"}, {**beat, "purpose": "cta"}]}}
    normalized = normalize_recipe_payload(drifted)
    assert [b["purpose"] for b in normalized["director_plan"]["beats"]] == [
        "hook", "feature", "usage", "feature", "identity", "closing"]


def test_plan_only_reply_is_wrapped_into_a_recipe_with_notes():
    plan_only = {"version": 1, "beats": [
        {**RECIPE["director_plan"]["beats"][0], "purpose": "spec"}, RECIPE["director_plan"]["beats"][1]]}
    client = OpenAICompatibleDirectorClient(settings(), transport=httpx.MockTransport(
        lambda _: reply(json.dumps(plan_only, ensure_ascii=False))))
    recipe = client.analyze_tutorial({"tutorial_text": "x", "content_category": "商品介绍"})
    assert recipe.notes == ["model_returned_director_plan_only_recipe_fields_derived"]
    assert recipe.target_duration_seconds == 5  # 1.2 s + 1.4 s rounded up to the 5 s floor
    assert [b.purpose for b in recipe.director_plan.beats] == ["hook", "closing"]


def test_user_turn_reminds_the_full_output_shape():
    text = OpenAICompatibleDirectorClient._user_text({"content_category": "商品介绍", "tutorial_text": "t"})
    assert "输出格式提醒" in text and "director_plan" in text and "hook|identity|feature|evidence|usage|closing" in text


def test_claim_guard_retries_once_and_bills_both_calls(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace
    from app.services.pipeline_service import PipelineService
    from app.schemas.analysis import EditRecipe

    def plan(narrations):
        beats = [{"purpose": "hook" if i == 0 else "closing" if i == len(narrations) - 1 else "feature",
                  "narration": n, "material_id": "m1", "source_start_seconds": i * 1.0, "source_end_seconds": i * 1.0 + 0.8,
                  "rationale": "r"} for i, n in enumerate(narrations)]
        return EditRecipe.model_validate({**RECIPE, "director_plan": {"version": 1, "beats": beats}})

    replies = [plan(["下午犯困", "整箱囤货更划算", "从这杯开始"]), plan(["下午犯困", "整箱囤货十瓶", "从这杯开始"])]
    calls = []

    class Director:
        configured = True
        model = "qwen3-vl-plus"
        endpoint = "e"
        credential_scope = "s"
        revision = "r"
        last_usage = None

        def analyze_tutorial(self, inputs, **kw):
            calls.append(inputs["tutorial_text"])
            self.last_usage = SimpleNamespace(workflow_run_id=f"run-{len(calls)}", input_tokens=100, output_tokens=10,
                                              total_tokens=110, elapsed_time=0, status="succeeded")
            return replies[len(calls) - 1]

    from app.schemas.editing import MediaAnalysis
    analyses = [MediaAnalysis(material_id="m1", source_path="m1.mov", duration_seconds=5, width=1080, height=1920, has_audio=False)]
    pipeline = PipelineService(Settings(data_dir=tmp_path), dify=SimpleNamespace(last_usage=None), director=Director())
    usage = []
    monkeypatch.setattr(pipeline, "_record_usage", lambda *a, **kw: usage.append(kw))
    task = SimpleNamespace(id="t1", tutorial_text="教程", cloud_processing_allowed=True, requirements_text="看包装",
                           content_type="商品介绍", materials=[])
    warnings = []
    result = pipeline._analyze_tutorial(None, task, analyses, tmp_path, [], warnings)

    assert len(calls) == 2 and "禁止词“划算”" in calls[1]
    assert [b.narration for b in result.director_plan.beats][1] == "整箱囤货十瓶"
    assert any("已按禁止项重写一次" in w for w in warnings)
    totals = {item["metric"]: item["quantity"] for item in usage}
    assert totals["total_tokens"] == 220  # both passes billed
    report = json.loads((tmp_path / "visual-input-evidence.json").read_text(encoding="utf-8"))
    assert report["claim_guard"] == {"first_pass": ["beat 2: 划算"], "retry": []}
