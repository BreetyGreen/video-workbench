from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.schemas.analysis import EditRecipe, ViralAnalysis


AnalysisModel = TypeVar("AnalysisModel", bound=BaseModel)


@dataclass(frozen=True)
class WorkflowUsage:
    workflow_run_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    elapsed_time: float = 0


class AnalysisOutputError(ValueError):
    def __init__(self, message: str, *, raw_response: str):
        super().__init__(message)
        self.raw_response = raw_response


class DifyClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ):
        self.settings = settings
        self._client = httpx.Client(
            base_url=settings.dify_base_url.rstrip("/") + "/" if settings.dify_base_url else "http://dify.invalid/",
            timeout=settings.dify_timeout_seconds,
            transport=transport,
        )
        self.last_usage: WorkflowUsage | None = None

    def status(self) -> dict[str, str]:
        if not self.settings.dify_base_url:
            return {"status": "not_configured", "reason": "missing_base_url"}
        missing = []
        if not self.settings.dify_tutorial_api_key:
            missing.append("tutorial")
        if not self.settings.dify_viral_api_key:
            missing.append("viral")
        if missing:
            return {
                "status": "not_configured" if len(missing) == 2 else "partially_configured",
                "reason": f"missing_{'_and_'.join(missing)}_api_key",
            }
        return {"status": "configured"}

    def _run(
        self,
        inputs: dict[str, object],
        output_model: type[AnalysisModel],
        *,
        api_key: str,
        workflow_name: str,
    ) -> AnalysisModel:
        self.last_usage = None
        if not self.settings.dify_base_url:
            raise RuntimeError("Dify is not configured: missing_base_url")
        if not api_key:
            raise RuntimeError(f"Dify {workflow_name} workflow is not configured: missing_api_key")

        response = self._client.post(
            "workflows/run",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "inputs": inputs,
                "response_mode": "blocking",
                "user": "automated-video-workbench",
            },
        )
        response.raise_for_status()
        data = response.json().get("data", {})
        self.last_usage = WorkflowUsage(
            workflow_run_id=str(data.get("workflow_run_id", "") or ""),
            input_tokens=int(data.get("input_tokens", 0) or 0),
            output_tokens=int(data.get("output_tokens", 0) or 0),
            total_tokens=int(data.get("total_tokens", 0) or 0),
            elapsed_time=float(data.get("elapsed_time", 0) or 0),
        )
        outputs = data.get("outputs", {})
        raw = outputs.get("text", outputs.get("result", ""))
        if not isinstance(raw, str):
            raw = json.dumps(raw, ensure_ascii=False)
        try:
            return output_model.model_validate_json(raw)
        except (ValidationError, ValueError, json.JSONDecodeError) as error:
            raise AnalysisOutputError(
                f"Dify returned invalid {output_model.__name__} JSON",
                raw_response=raw,
            ) from error

    def analyze_tutorial(self, inputs: dict[str, object]) -> EditRecipe:
        return self._run(
            inputs,
            EditRecipe,
            api_key=self.settings.dify_tutorial_api_key,
            workflow_name="tutorial",
        )

    def analyze_viral(self, inputs: dict[str, object]) -> ViralAnalysis:
        return self._run(
            inputs,
            ViralAnalysis,
            api_key=self.settings.dify_viral_api_key,
            workflow_name="viral",
        )
