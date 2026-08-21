import httpx

from app.adapters.seedance import SeedanceClient


def test_seedance_is_disabled_without_key_and_model():
    assert SeedanceClient(api_key="", model="").configured is False


def test_seedance_submits_vertical_content_generation_task():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "generation-1", "status": "queued"})

    client = SeedanceClient(
        api_key="ark-key",
        model="seedance-model-endpoint",
        transport=httpx.MockTransport(handler),
    )
    task = client.create_vertical_clip("一只猫咪主动蹭梳毛刷")

    assert task.id == "generation-1"
    assert requests[0].headers["authorization"] == "Bearer ark-key"
    payload = __import__("json").loads(requests[0].content)
    assert payload["model"] == "seedance-model-endpoint"
    assert payload["ratio"] == "9:16"
    assert payload["content"][0]["text"] == "一只猫咪主动蹭梳毛刷"
