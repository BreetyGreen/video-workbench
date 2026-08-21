from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class SeedanceTask:
    id: str
    status: str


class SeedanceClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
        timeout_seconds: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model)

    def status(self) -> dict[str, str]:
        missing = []
        if not self.api_key:
            missing.append("api_key")
        if not self.model:
            missing.append("model_endpoint")
        return {
            "status": "configured" if self.configured else "not_configured",
            "provider": "volcengine_seedance",
            "reason": ",".join(missing),
        }

    def create_vertical_clip(self, prompt: str) -> SeedanceTask:
        if not self.configured:
            raise RuntimeError("seedance_not_configured")
        normalized = prompt.strip()
        if not normalized:
            raise ValueError("prompt_required")
        with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
            response = client.post(
                f"{self.base_url}/contents/generations/tasks",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "content": [{"type": "text", "text": normalized}],
                    "ratio": "9:16",
                    "duration": 5,
                    "watermark": False,
                },
            )
            response.raise_for_status()
            payload = response.json()
        return SeedanceTask(id=str(payload.get("id") or ""), status=str(payload.get("status") or "queued"))

    def get_task(self, task_id: str) -> dict[str, object]:
        if not self.configured:
            raise RuntimeError("seedance_not_configured")
        with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
            response = client.get(
                f"{self.base_url}/contents/generations/tasks/{task_id}",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            return response.json()
