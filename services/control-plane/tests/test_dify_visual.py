from __future__ import annotations

import copy
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from app.adapters.dify import DifyClient, WorkflowUsage
from app.config import Settings


def settings(**overrides) -> Settings:
    values = {
        "dify_base_url": "http://dify.test/v1",
        "dify_tutorial_api_key": "tutorial-key",
        "dify_viral_api_key": "viral-key",
    }
    values.update(overrides)
    return Settings(**values)


def recipe_json() -> str:
    return json.dumps(
        {
            "hook_rules": ["result first"],
            "target_duration_seconds": 20,
            "pacing": [{"from_second": 0, "to_second": 3, "instruction": "open"}],
            "track_layout": ["video"],
            "caption_style": "plain",
            "audio_rules": [],
            "prohibited_elements": [],
            "qa_thresholds": {"max_silence_seconds": 1, "max_black_seconds": 0.5},
        }
    )


def make_image(path: Path, *, image_format: str = "JPEG", size: tuple[int, int] = (32, 24)) -> bytes:
    Image.new("RGB", size, (21, 82, 143)).save(path, format=image_format)
    return path.read_bytes()


def test_tutorial_uploads_real_images_and_passes_exact_file_list_without_mutating_inputs(tmp_path: Path):
    first = tmp_path / "unsafe original name.jpg"
    second = tmp_path / "another.png"
    first_bytes = make_image(first)
    second_bytes = make_image(second, image_format="PNG")
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = request.read()
        assert request.headers["authorization"] == "Bearer tutorial-key"
        if request.url.path == "/v1/files/upload":
            expected_index = len(calls)
            expected_name = f"frame-{expected_index:03d}." + ("jpg" if expected_index == 1 else "png")
            expected_bytes = first_bytes if expected_index == 1 else second_bytes
            assert b'name="user"' in body
            assert b"automated-video-workbench" in body
            assert f'filename="{expected_name}"'.encode() in body
            assert b"unsafe original name" not in body
            assert expected_bytes in body
            return httpx.Response(201, json={"id": f"upload-{expected_index}"})
        assert request.url.path == "/v1/workflows/run"
        payload = json.loads(body)
        assert payload["user"] == "automated-video-workbench"
        assert payload["inputs"]["visual_frames"] == [
            {"type": "image", "transfer_method": "local_file", "upload_file_id": "upload-1"},
            {"type": "image", "transfer_method": "local_file", "upload_file_id": "upload-2"},
        ]
        return httpx.Response(200, json={"workflow_run_id": "top-run", "data": {"status": "succeeded", "outputs": {"text": recipe_json()}}})

    inputs = {"text": "tutorial", "nested": {"keep": True}}
    original = copy.deepcopy(inputs)
    client = DifyClient(settings(), transport=httpx.MockTransport(handler))

    client.analyze_tutorial(inputs, image_paths=[first, second])

    assert inputs == original
    assert [request.url.path for request in calls] == ["/v1/files/upload", "/v1/files/upload", "/v1/workflows/run"]
    assert client.last_usage == WorkflowUsage(workflow_run_id="top-run")


def test_tutorial_without_images_sends_no_files_input():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/workflows/run"
        assert "visual_frames" not in json.loads(request.read())["inputs"]
        return httpx.Response(200, json={"data": {"id": "data-run", "status": "succeeded", "outputs": {"text": recipe_json()}}})

    client = DifyClient(settings(), transport=httpx.MockTransport(handler))
    client.analyze_tutorial({"text": "tutorial", "visual_frames": [{"upload_file_id": "caller-supplied"}]})
    assert client.last_usage == WorkflowUsage(workflow_run_id="data-run")


@pytest.mark.parametrize("missing", ["base", "key"])
def test_missing_tutorial_configuration_makes_no_request(tmp_path: Path, missing: str):
    image_path = tmp_path / "frame.jpg"
    make_image(image_path)
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(500)

    configured = settings(dify_base_url="") if missing == "base" else settings(dify_tutorial_api_key="")
    client = DifyClient(configured, transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="not configured"):
        client.analyze_tutorial({}, image_paths=[image_path])
    assert requests == 0


@pytest.mark.parametrize("invalid_kind", ["missing", "not_image", "too_large", "too_wide"])
def test_invalid_image_list_is_rejected_before_any_request(tmp_path: Path, invalid_kind: str):
    image_path = tmp_path / "frame.jpg"
    if invalid_kind == "missing":
        pass
    elif invalid_kind == "not_image":
        image_path.write_bytes(b"not an image")
    elif invalid_kind == "too_large":
        make_image(image_path)
        image_path.write_bytes(image_path.read_bytes() + b"x" * (2 * 1024 * 1024))
    else:
        make_image(image_path, size=(4097, 1))
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(500)

    client = DifyClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="image"):
        client.analyze_tutorial({}, image_paths=[image_path])
    assert requests == 0


def test_more_than_eight_images_is_rejected_before_any_request(tmp_path: Path):
    paths = []
    for index in range(9):
        path = tmp_path / f"{index}.png"
        make_image(path, image_format="PNG")
        paths.append(path)
    client = DifyClient(settings(), transport=httpx.MockTransport(lambda _: pytest.fail("request made")))

    with pytest.raises(ValueError, match="8"):
        client.analyze_tutorial({}, image_paths=paths)


def test_image_validation_uses_a_bounded_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    image_path = tmp_path / "oversized.jpg"
    image_path.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    monkeypatch.setattr(Path, "read_bytes", lambda _: pytest.fail("unbounded read_bytes used"))
    client = DifyClient(settings(), transport=httpx.MockTransport(lambda _: pytest.fail("request made")))

    with pytest.raises(ValueError, match="image size"):
        client.analyze_tutorial({}, image_paths=[image_path])


def test_decompression_bomb_is_reported_as_invalid_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    image_path = tmp_path / "frame.png"
    make_image(image_path, image_format="PNG")

    def reject_image(*_: object, **__: object):
        raise Image.DecompressionBombError("unsafe dimensions")

    monkeypatch.setattr("app.adapters.dify.Image.open", reject_image)
    client = DifyClient(settings(), transport=httpx.MockTransport(lambda _: pytest.fail("request made")))

    with pytest.raises(ValueError, match="Invalid image file"):
        client.analyze_tutorial({}, image_paths=[image_path])


def test_truncated_jpeg_is_rejected_before_any_request(tmp_path: Path):
    image_path = tmp_path / "truncated.jpg"
    make_image(image_path, size=(64, 64))
    image_path.write_bytes(image_path.read_bytes()[:-40])
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(500)

    client = DifyClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="Invalid image file"):
        client.analyze_tutorial({}, image_paths=[image_path])
    assert requests == 0


def test_upload_error_stops_workflow_and_clears_stale_usage(tmp_path: Path):
    image_path = tmp_path / "frame.jpg"
    make_image(image_path)
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(503, text="unavailable")

    client = DifyClient(settings(), transport=httpx.MockTransport(handler))
    client.last_usage = WorkflowUsage(workflow_run_id="stale", total_tokens=99)

    with pytest.raises(httpx.HTTPStatusError):
        client.analyze_tutorial({}, image_paths=[image_path])

    assert paths == ["/v1/files/upload"]
    assert client.last_usage is None


@pytest.mark.parametrize("payload", [{}, {"id": ""}, {"id": None}])
def test_empty_upload_id_is_rejected_without_workflow(tmp_path: Path, payload: dict[str, object]):
    image_path = tmp_path / "frame.png"
    make_image(image_path, image_format="PNG")
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json=payload)

    client = DifyClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="upload ID"):
        client.analyze_tutorial({}, image_paths=[image_path])
    assert paths == ["/v1/files/upload"]


def test_failed_workflow_retains_usage_but_does_not_trust_outputs():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "workflow_run_id": "legacy-run",
                    "status": "failed",
                    "error": "model failed",
                    "total_tokens": 17,
                    "elapsed_time": 2.5,
                    "outputs": {"text": recipe_json()},
                }
            },
        )

    client = DifyClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="failed"):
        client.analyze_tutorial({})
    assert client.last_usage == WorkflowUsage(
        workflow_run_id="legacy-run",
        total_tokens=17,
        elapsed_time=2.5,
        status="failed",
    )


def test_stopped_workflow_retains_returned_status_in_usage():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": {"id": "stopped-run", "status": "stopped", "total_tokens": 3}},
        )

    client = DifyClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="stopped"):
        client.analyze_tutorial({})
    assert client.last_usage == WorkflowUsage(
        workflow_run_id="stopped-run",
        total_tokens=3,
        status="stopped",
    )
