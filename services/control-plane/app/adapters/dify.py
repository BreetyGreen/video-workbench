from __future__ import annotations

import json
from io import BytesIO
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import httpx
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.schemas.analysis import EditRecipe, ViralAnalysis


AnalysisModel = TypeVar("AnalysisModel", bound=BaseModel)
_DIFY_USER = "automated-video-workbench"
_MAX_IMAGE_COUNT = 8
_MAX_IMAGE_BYTES = 2 * 1024 * 1024
_MAX_IMAGE_DIMENSION = 4096


@dataclass(frozen=True)
class WorkflowUsage:
    workflow_run_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    elapsed_time: float = 0
    status: str = "succeeded"


def validate_visual_images(image_paths: list[Path]) -> list[tuple[bytes, str]]:
    """Bounded, decoded JPEG/PNG frames shared by every director transport."""
    if len(image_paths) > _MAX_IMAGE_COUNT:
        raise ValueError(f"Visual input accepts at most {_MAX_IMAGE_COUNT} images")

    validated: list[tuple[bytes, str]] = []
    for path in image_paths:
        try:
            with path.open("rb") as image_file:
                content = image_file.read(_MAX_IMAGE_BYTES + 1)
        except (OSError, TypeError, AttributeError) as error:
            raise ValueError("Invalid image path") from error
        if not content or len(content) > _MAX_IMAGE_BYTES:
            raise ValueError("Invalid image size")
        try:
            with Image.open(BytesIO(content)) as image:
                image_format = image.format
                width, height = image.size
                if image_format not in {"JPEG", "PNG"}:
                    raise ValueError("Invalid image format")
                if width > _MAX_IMAGE_DIMENSION or height > _MAX_IMAGE_DIMENSION:
                    raise ValueError("Invalid image dimensions")
                image.load()
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError, ValueError) as error:
            raise ValueError("Invalid image file") from error
        validated.append((content, "jpg" if image_format == "JPEG" else "png"))
    return validated


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
                "user": _DIFY_USER,
            },
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", {})
        if not isinstance(data, dict):
            data = {}

        def field(name: str, default: object = 0) -> object:
            return data.get(name, payload.get(name, default))

        def integer(name: str) -> int:
            try:
                return int(field(name) or 0)
            except (TypeError, ValueError):
                return 0

        def number(name: str) -> float:
            try:
                return float(field(name) or 0)
            except (TypeError, ValueError):
                return 0

        status = str(field("status", "") or "succeeded").lower()
        self.last_usage = WorkflowUsage(
            workflow_run_id=str(
                payload.get("workflow_run_id")
                or data.get("id")
                or data.get("workflow_run_id")
                or ""
            ),
            input_tokens=integer("input_tokens"),
            output_tokens=integer("output_tokens"),
            total_tokens=integer("total_tokens"),
            elapsed_time=number("elapsed_time"),
            status=status,
        )
        if status in {"failed", "stopped"}:
            raise RuntimeError(f"Dify {workflow_name} workflow {status}")
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

    def _validate_images(self, image_paths: list[Path]) -> list[tuple[bytes, str]]:
        return validate_visual_images(image_paths)

    def analyze_tutorial(
        self,
        inputs: dict[str, object],
        *,
        image_paths: list[Path] | None = None,
    ) -> EditRecipe:
        self.last_usage = None
        if not self.settings.dify_base_url:
            raise RuntimeError("Dify is not configured: missing_base_url")
        if not self.settings.dify_tutorial_api_key:
            raise RuntimeError("Dify tutorial workflow is not configured: missing_api_key")

        validated_images = self._validate_images(image_paths or [])
        workflow_inputs = dict(inputs)
        workflow_inputs.pop("visual_frames", None)
        if validated_images:
            uploaded_files = []
            headers = {"Authorization": f"Bearer {self.settings.dify_tutorial_api_key}"}
            for index, (content, extension) in enumerate(validated_images, start=1):
                response = self._client.post(
                    "files/upload",
                    headers=headers,
                    data={"user": _DIFY_USER},
                    files={
                        "file": (
                            f"frame-{index:03d}.{extension}",
                            content,
                            "image/jpeg" if extension == "jpg" else "image/png",
                        )
                    },
                )
                response.raise_for_status()
                upload_id = response.json().get("id")
                if not isinstance(upload_id, str) or not upload_id.strip():
                    raise ValueError("Dify returned an invalid upload ID")
                uploaded_files.append(
                    {
                        "type": "image",
                        "transfer_method": "local_file",
                        "upload_file_id": upload_id,
                    }
                )
            workflow_inputs["visual_frames"] = uploaded_files

        return self._run(
            workflow_inputs,
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
